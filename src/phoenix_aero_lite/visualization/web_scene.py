"""Standalone browser scene export through the official PyVista/Trame path."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import json
import math
from pathlib import Path
from threading import RLock

import numpy as np
import pyvista as pv


_SCENE_EXPORT_LOCK = RLock()


def _serialized_scene_export(function):
    """Use one process-wide guard for all PyVista/VTK browser exports."""

    @wraps(function)
    def guarded(*args, **kwargs):
        with _SCENE_EXPORT_LOCK:
            return function(*args, **kwargs)

    return guarded


@dataclass(frozen=True, slots=True)
class InteractiveScene:
    output_path: Path
    point_count: int
    cell_count: int
    scalar_name: str | None
    scalar_range: tuple[float, float] | None
    selectable_surface_tags: tuple[int, ...] = ()


@_serialized_scene_export
def export_pressure_surface(
    source_path: Path,
    output_path: Path,
    field: str,
    *,
    range_min: float | None = None,
    range_max: float | None = None,
) -> InteractiveScene:
    """Export Cp or static pressure without conflating names or units."""

    fields = {
        "cp": ("Pressure_Coefficient", "Cp"),
        "pressure": ("Pressure", "Pressure (Pa)"),
    }
    try:
        scalar_name, scalar_title = fields[field]
    except KeyError:
        raise ValueError("PRESSURE_FIELD_INVALID") from None
    return export_interactive_surface(
        source_path,
        output_path,
        scalar_name=scalar_name,
        scalar_title=scalar_title,
        scalar_range=_validated_manual_range(range_min, range_max),
    )


@_serialized_scene_export
def export_y_plus_surface(
    source_path: Path,
    output_path: Path,
    *,
    range_min: float | None = None,
    range_max: float | None = None,
) -> InteractiveScene:
    """Export the solver-computed wall Y+ field without substituting its target."""

    dataset = pv.read(Path(source_path).resolve(strict=True))
    if isinstance(dataset, pv.MultiBlock):
        dataset = dataset.combine()
    scalar_name = next(
        (
            str(name)
            for name in dataset.array_names
            if "".join(character for character in name.lower() if character.isalnum())
            == "yplus"
        ),
        None,
    )
    if scalar_name is None:
        raise ValueError("Y_PLUS_FIELD_MISSING")
    values = np.asarray(dataset.get_array(scalar_name))
    finite_values = values[np.isfinite(values)]
    if (
        values.ndim != 1
        or finite_values.size == 0
        or np.any(finite_values < 0.0)
    ):
        raise ValueError("Y_PLUS_FIELD_INVALID")
    return export_interactive_surface(
        source_path,
        output_path,
        scalar_name=scalar_name,
        scalar_title="Y+",
        scalar_range=_validated_manual_range(range_min, range_max),
    )


@_serialized_scene_export
def export_velocity_slice(
    source_path: Path,
    output_path: Path,
    preset: str,
    *,
    position: float = 0.0,
    opacity: float = 1.0,
    visible: bool = True,
) -> InteractiveScene:
    """Export a preset plane colored by the magnitude of the real velocity field."""

    if preset not in {"longitudinal", "wing", "wake"}:
        raise ValueError("VELOCITY_SLICE_PRESET_INVALID")
    if not math.isfinite(position) or not -1.0 <= position <= 1.0:
        raise ValueError("VELOCITY_SLICE_POSITION_INVALID")
    if not math.isfinite(opacity) or not 0.05 <= opacity <= 1.0:
        raise ValueError("VELOCITY_SLICE_OPACITY_INVALID")
    dataset = _point_velocity_dataset(source_path)
    bounds = dataset.bounds
    center = np.asarray(dataset.center, dtype=float)
    if preset == "longitudinal":
        normal = (0.0, 1.0, 0.0)
        origin = center.copy()
        origin[1] += position * 0.5 * (bounds.y_max - bounds.y_min)
    elif preset == "wing":
        normal = (0.0, 0.0, 1.0)
        origin = center.copy()
        origin[2] += position * 0.5 * (bounds.z_max - bounds.z_min)
    else:
        normal = (1.0, 0.0, 0.0)
        origin = center.copy()
        origin[0] = bounds.x_min + (0.7 + 0.25 * position) * (
            bounds.x_max - bounds.x_min
        )
    sliced = dataset.slice(normal=normal, origin=origin)
    if sliced.n_points <= 0 or sliced.n_cells <= 0:
        raise ValueError("VELOCITY_SLICE_EMPTY")
    return _export_colored_dataset(
        sliced,
        output_path,
        scalar_name="Velocity_Magnitude",
        scalar_title="Velocity (m/s)",
        opacity=opacity if visible else 0.0,
    )


@_serialized_scene_export
def export_streamline_scene(
    volume_path: Path,
    surface_path: Path,
    output_path: Path,
    *,
    flow_direction: tuple[float, float, float],
    density: str,
    line_width: float = 3.0,
    opacity: float = 1.0,
    visible: bool = True,
) -> InteractiveScene:
    """Seed a bounded plane upstream of the aircraft and integrate downstream."""

    resolutions = {"sparse": 5, "standard": 9, "dense": 14}
    try:
        resolution = resolutions[density]
    except KeyError:
        raise ValueError("STREAMLINE_DENSITY_INVALID") from None
    if not math.isfinite(line_width) or not 1.0 <= line_width <= 8.0:
        raise ValueError("STREAMLINE_WIDTH_INVALID")
    if not math.isfinite(opacity) or not 0.05 <= opacity <= 1.0:
        raise ValueError("STREAMLINE_OPACITY_INVALID")
    direction = np.asarray(flow_direction, dtype=float)
    if direction.shape != (3,) or not np.all(np.isfinite(direction)):
        raise ValueError("STREAMLINE_DIRECTION_INVALID")
    magnitude = float(np.linalg.norm(direction))
    if magnitude <= 0:
        raise ValueError("STREAMLINE_DIRECTION_INVALID")
    direction /= magnitude

    volume = _point_velocity_dataset(volume_path)
    surface = pv.read(Path(surface_path).resolve(strict=True)).extract_surface(
        algorithm="dataset_surface"
    )
    if surface.n_points <= 0:
        raise ValueError("STREAMLINE_SURFACE_EMPTY")
    aircraft_center = np.asarray(surface.center, dtype=float)
    corners = _bounds_corners(surface.bounds)
    projections = corners @ direction
    longitudinal_extent = float(np.ptp(projections))
    diagonal = max(float(surface.length), 1e-6)
    seed_center = aircraft_center - direction * (
        0.75 * longitudinal_extent + 0.10 * diagonal
    )
    plane_size = 1.35 * diagonal
    seeds = pv.Plane(
        center=seed_center,
        direction=direction,
        i_size=plane_size,
        j_size=plane_size,
        i_resolution=resolution,
        j_resolution=resolution,
    )
    lines = volume.streamlines_from_source(
        seeds,
        vectors="Velocity",
        integration_direction="forward",
        max_steps=2_000,
    )
    if lines.n_points <= 0 or lines.n_cells <= 0:
        raise ValueError("STREAMLINES_EMPTY")
    velocity = np.asarray(lines.point_data["Velocity"], dtype=float)
    lines.point_data["Velocity_Magnitude"] = np.linalg.norm(velocity, axis=1)
    low, high = _finite_range(lines, "Velocity_Magnitude")
    output = _html_output_path(output_path)
    plotter = pv.Plotter(off_screen=True)
    try:
        plotter.add_mesh(surface, color="#cbd4de", opacity=0.42)
        plotter.add_mesh(
            lines,
            scalars="Velocity_Magnitude",
            line_width=line_width,
            opacity=opacity if visible else 0.0,
            scalar_bar_args={"title": "Velocity (m/s)", "color": "white"},
        )
        plotter.add_axes()
        plotter.set_background("#0b1525")
        plotter.view_isometric()
        plotter.reset_camera()
        plotter.export_html(output)
    finally:
        plotter.close()
    _sanitize_standalone_html(output)
    _verify_html(output)
    _inject_scene_controls(
        output, "Velocity_Magnitude", "Velocity (m/s)", (low, high)
    )
    return InteractiveScene(
        output, lines.n_points, lines.n_cells, "Velocity_Magnitude", (low, high)
    )


@_serialized_scene_export
def export_interactive_surface(
    source_path: Path,
    output_path: Path,
    *,
    scalar_name: str | None = None,
    scalar_title: str | None = None,
    scalar_range: tuple[float, float] | None = None,
) -> InteractiveScene:
    """Export a real VTK dataset as a self-contained interactive HTML scene."""

    source = Path(source_path).resolve(strict=True)
    output = Path(output_path).resolve(strict=False)
    if output.suffix.casefold() != ".html":
        raise ValueError("WEB_SCENE_OUTPUT_MUST_BE_HTML")
    dataset = pv.read(source)
    surface = (
        dataset
        if isinstance(dataset, pv.PolyData)
        else dataset.extract_surface(algorithm="dataset_surface")
    )
    if surface.n_points <= 0 or surface.n_cells <= 0:
        raise ValueError("WEB_SCENE_EMPTY_DATASET")

    if scalar_name is not None:
        if scalar_name not in surface.array_names:
            raise ValueError("WEB_SCENE_SCALAR_MISSING")
        low, high = (float(value) for value in surface.get_data_range(scalar_name))
        if not math.isfinite(low) or not math.isfinite(high):
            raise ValueError("WEB_SCENE_SCALAR_NONFINITE")
        automatic_range = (low, high)
        scalar_range = scalar_range or automatic_range

    output.parent.mkdir(parents=True, exist_ok=True)
    plotter = pv.Plotter(off_screen=True)
    try:
        options: dict[str, object] = {
            "color": "#d7dee8",
            "smooth_shading": True,
        }
        if scalar_name is not None:
            options.update(
                scalars=scalar_name,
                cmap="coolwarm",
                show_scalar_bar=True,
                clim=scalar_range,
                scalar_bar_args={
                    "title": scalar_title or scalar_name,
                    "color": "white",
                },
            )
        surface_tags: tuple[int, ...] = ()
        if scalar_name is None and "CellEntityIds" in surface.cell_data:
            surface_tags = tuple(
                int(value)
                for value in np.unique(surface.cell_data["CellEntityIds"])
            )
            for tag in surface_tags:
                face = surface.extract_cells(
                    np.asarray(surface.cell_data["CellEntityIds"]) == tag
                )
                plotter.add_mesh(face, **options)
        else:
            plotter.add_mesh(surface, **options)
        plotter.add_axes()
        plotter.set_background("#0b1525")
        plotter.view_isometric()
        plotter.reset_camera()
        plotter.export_html(output)
    finally:
        plotter.close()

    _sanitize_standalone_html(output)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("WEB_SCENE_EXPORT_FAILED")
    if surface_tags:
        _inject_surface_picker(output, surface_tags)
    if scalar_name is not None and scalar_range is not None:
        _inject_scene_controls(
            output, scalar_name, scalar_title or scalar_name, scalar_range
        )
    return InteractiveScene(
        output_path=output,
        point_count=surface.n_points,
        cell_count=surface.n_cells,
        scalar_name=scalar_name,
        scalar_range=scalar_range,
        selectable_surface_tags=surface_tags,
    )


def _point_velocity_dataset(source_path: Path) -> pv.DataSet:
    dataset = pv.read(Path(source_path).resolve(strict=True))
    if isinstance(dataset, pv.MultiBlock):
        dataset = dataset.combine()
    if "Velocity" in dataset.cell_data and "Velocity" not in dataset.point_data:
        dataset = dataset.cell_data_to_point_data()
    if "Velocity" not in dataset.point_data:
        raise ValueError("VELOCITY_FIELD_MISSING")
    velocity = np.asarray(dataset.point_data["Velocity"], dtype=float)
    if (
        velocity.ndim != 2
        or velocity.shape[1] != 3
        or not np.all(np.isfinite(velocity))
    ):
        raise ValueError("VELOCITY_FIELD_INVALID")
    dataset.point_data["Velocity_Magnitude"] = np.linalg.norm(velocity, axis=1)
    return dataset


def _export_colored_dataset(
    dataset: pv.DataSet,
    output_path: Path,
    *,
    scalar_name: str,
    scalar_title: str,
    opacity: float = 1.0,
) -> InteractiveScene:
    low, high = _finite_range(dataset, scalar_name)
    output = _html_output_path(output_path)
    plotter = pv.Plotter(off_screen=True)
    try:
        plotter.add_mesh(
            dataset,
            scalars=scalar_name,
            show_scalar_bar=True,
            opacity=opacity,
            scalar_bar_args={"title": scalar_title, "color": "white"},
        )
        plotter.add_axes()
        plotter.set_background("#0b1525")
        plotter.view_isometric()
        plotter.reset_camera()
        plotter.export_html(output)
    finally:
        plotter.close()
    _sanitize_standalone_html(output)
    _verify_html(output)
    _inject_scene_controls(output, scalar_name, scalar_title, (low, high))
    return InteractiveScene(
        output, dataset.n_points, dataset.n_cells, scalar_name, (low, high)
    )


def _finite_range(dataset: pv.DataSet, scalar_name: str) -> tuple[float, float]:
    low, high = (float(value) for value in dataset.get_data_range(scalar_name))
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError("WEB_SCENE_SCALAR_NONFINITE")
    return low, high


def _html_output_path(path: Path) -> Path:
    output = Path(path).resolve(strict=False)
    if output.suffix.casefold() != ".html":
        raise ValueError("WEB_SCENE_OUTPUT_MUST_BE_HTML")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _verify_html(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("WEB_SCENE_EXPORT_FAILED")


def _sanitize_standalone_html(path: Path) -> None:
    """Keep the official PyVista export local under the application's CSP."""

    text = path.read_text(encoding="utf-8")
    remote_favicon = "https://kitware.github.io/vtk-js/icon/favicon-${e}x${e}.png"
    local_favicon = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
        "AScY42YAAAAASUVORK5CYII="
    )
    if remote_favicon in text:
        path.write_text(
            text.replace(remote_favicon, local_favicon),
            encoding="utf-8",
            newline="",
        )


def _bounds_corners(bounds: pv.BoundsTuple) -> np.ndarray:
    return np.asarray(
        [
            (x, y, z)
            for x in (bounds.x_min, bounds.x_max)
            for y in (bounds.y_min, bounds.y_max)
            for z in (bounds.z_min, bounds.z_max)
        ],
        dtype=float,
    )


def _inject_surface_picker(path: Path, surface_tags: tuple[int, ...]) -> None:
    """Add a thin interaction layer over the bundled official VTK.js viewer."""

    tags = json.dumps(surface_tags)
    script = f"""
<script id="phoenix-surface-picker">
(() => {{
  const surfaceTags = {tags};
  const normalColor = [0.843, 0.871, 0.910];
  const selectedColor = [1.0, 0.55, 0.08];
  let actors = [];
  let selected = new Set();
  let pickMode = 'wing';

  function scene() {{
    const renderWindow = window.global && window.global.renderWindow;
    if (!renderWindow) return null;
    const windows = [renderWindow, ...renderWindow.getChildRenderWindows()];
    const renderers = windows.flatMap(item => item.getRenderers());
    const renderer = renderers.find(item => item.getActors().length >= surfaceTags.length);
    const view = renderWindow.getInteractor().getView();
    if (!renderer || !view) return null;
    actors = renderer.getActors().slice(0, surfaceTags.length);
    return {{ renderWindow, renderer, view }};
  }}

  function recolor(current) {{
    const state = current || scene();
    if (!state || actors.length !== surfaceTags.length) return;
    actors.forEach((actor, index) => {{
      actor.getProperty().setColor(...(selected.has(surfaceTags[index]) ? selectedColor : normalColor));
    }});
    state.renderWindow.render();
  }}

  async function pick(event) {{
    const state = scene();
    if (!state) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const size = state.view.getSize();
    const x = Math.round((event.clientX - rect.left) * size[0] / rect.width);
    const y = Math.round((rect.bottom - event.clientY) * size[1] / rect.height);
    const selector = state.view.getSelector();
    selector.setFieldAssociation(1);
    selector.attach(state.view, state.renderer);
    const nodes = await selector.selectAsync(state.renderer, x, y, x, y);
    if (!nodes.length) return;
    const prop = nodes[0].getProperties().prop;
    const actorIndex = actors.indexOf(prop);
    if (actorIndex < 0 || actorIndex >= surfaceTags.length) return;
    const tag = surfaceTags[actorIndex];
    if (pickMode === 'nose' || pickMode === 'up') {{
      const data = prop.getMapper().getInputData();
      const selection = nodes[0].getSelectionList();
      const id = selection && selection.length ? Number(selection[0]) : -1;
      if (!data || id < 0) return;
      data.buildCells();
      const cell = data.getCellPoints(id);
      const pointIds = cell && cell.cellPointIds ? Array.from(cell.cellPointIds) : [];
      const coordinates = data.getPoints().getData();
      if (!pointIds.length || !coordinates) return;
      const position = [0, 1, 2].map(component =>
        pointIds.reduce((sum, pointId) => sum + coordinates[pointId * 3 + component], 0) / pointIds.length
      );
      window.parent.postMessage({{
        type: 'phoenix-orientation-point', mode: pickMode, position, surfaceTag: tag,
      }}, window.location.origin);
      pickMode = 'wing';
      return;
    }}
    if (selected.has(tag)) selected.delete(tag); else selected.add(tag);
    recolor(state);
    window.parent.postMessage({{
      type: 'phoenix-surface-selection',
      tags: Array.from(selected).sort((a, b) => a - b),
    }}, window.location.origin);
  }}

  function ready() {{
    const state = scene();
    const root = document.querySelector('#vtk-root');
    if (!state || !root || actors.length !== surfaceTags.length) {{
      window.setTimeout(ready, 100);
      return;
    }}
    let start = null;
    root.addEventListener('pointerdown', event => {{ start = [event.clientX, event.clientY]; }});
    root.addEventListener('pointerup', event => {{
      if (!start || Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 4) return;
      pick(event).catch(error => window.parent.postMessage({{
        type: 'phoenix-surface-pick-error', detail: String(error)
      }}, window.location.origin));
    }});
    window.parent.postMessage({{ type: 'phoenix-picker-ready', surfaceCount: surfaceTags.length }}, window.location.origin);
  }}

  window.addEventListener('message', event => {{
    if (event.origin !== window.location.origin) return;
    const data = event.data || {{}};
    if (data.type === 'phoenix-set-surface-selection') {{
      selected = new Set((data.tags || []).map(Number));
      recolor();
      return;
    }}
    if (data.type === 'phoenix-pick-mode' && ['wing', 'nose', 'up'].includes(data.mode)) {{
      pickMode = data.mode;
      return;
    }}
    const state = scene(); if (!state) return;
    if (data.type === 'phoenix-camera') {{
      const bounds=state.renderer.computeVisiblePropBounds(), c=[(bounds[0]+bounds[1])/2,(bounds[2]+bounds[3])/2,(bounds[4]+bounds[5])/2], d=Math.max(bounds[1]-bounds[0],bounds[3]-bounds[2],bounds[5]-bounds[4])*3||3;
      if(data.command==='reset') state.renderer.resetCamera();
      else {{ const settings={{top:[[c[0],c[1],c[2]+d],[0,1,0]],front:[[c[0]-d,c[1],c[2]],[0,0,1]],side:[[c[0],c[1]+d,c[2]],[0,0,1]],isometric:[[c[0]+d,c[1]+d,c[2]+d],[0,0,1]]}}[data.command]; if(settings){{const cam=state.renderer.getActiveCamera();cam.setPosition(...settings[0]);cam.setFocalPoint(...c);cam.setViewUp(...settings[1]);state.renderer.resetCamera();}} }}
      state.renderWindow.render();
    }}
    if (data.type === 'phoenix-screenshot') Promise.resolve(state.renderWindow.captureImages()).then(images => window.parent.postMessage({{type:'phoenix-screenshot-ready',image:images&&images[0]}},window.location.origin));
  }});
  ready();
}})();
</script>
"""
    html = path.read_text(encoding="utf-8")
    if "</body>" not in html:
        raise RuntimeError("WEB_SCENE_EXPORT_FAILED")
    path.write_text(html.replace("</body>", script + "\n</body>"), encoding="utf-8")


def _validated_manual_range(
    range_min: float | None, range_max: float | None
) -> tuple[float, float] | None:
    if range_min is None and range_max is None:
        return None
    if (
        range_min is None
        or range_max is None
        or not math.isfinite(range_min)
        or not math.isfinite(range_max)
        or range_min >= range_max
    ):
        raise ValueError("SCALAR_RANGE_INVALID")
    return float(range_min), float(range_max)


def _inject_scene_controls(
    path: Path,
    scalar_name: str,
    scalar_title: str,
    scalar_range: tuple[float, float],
) -> None:
    """Expose camera, scalar range, screenshot and point probing via VTK.js."""

    metadata = json.dumps(
        {
            "scalarName": scalar_name,
            "scalarTitle": scalar_title,
            "scalarRange": list(scalar_range),
        },
        ensure_ascii=False,
    )
    script = f"""
<script id="phoenix-scene-controls">
(() => {{
  const metadata = {metadata};
  function scene() {{
    const rw = window.global && window.global.renderWindow;
    if (!rw) return null;
    const renderer = rw.getRenderers().find(item => item.getActors().length);
    const view = rw.getInteractor().getView();
    return renderer && view ? {{ rw, renderer, view, actors: renderer.getActors() }} : null;
  }}
  function boundsCenter(renderer) {{
    const b = renderer.computeVisiblePropBounds();
    return {{ center:[(b[0]+b[1])/2,(b[2]+b[3])/2,(b[4]+b[5])/2], size:Math.max(b[1]-b[0],b[3]-b[2],b[5]-b[4]) || 1 }};
  }}
  function camera(command) {{
    const state=scene(); if(!state) return;
    if(command==='reset') {{ state.renderer.resetCamera(); state.rw.render(); return; }}
    const info=boundsCenter(state.renderer), c=info.center, d=info.size*3, cam=state.renderer.getActiveCamera();
    const settings={{top:[[c[0],c[1],c[2]+d],[0,1,0]],front:[[c[0]-d,c[1],c[2]],[0,0,1]],side:[[c[0],c[1]+d,c[2]],[0,0,1]],isometric:[[c[0]+d,c[1]+d,c[2]+d],[0,0,1]]}}[command];
    if(!settings)return; cam.setPosition(...settings[0]); cam.setFocalPoint(...c); cam.setViewUp(...settings[1]); state.renderer.resetCamera(); state.rw.render();
  }}
  function scalarRange(minimum,maximum) {{
    const state=scene(); if(!state||!Number.isFinite(minimum)||!Number.isFinite(maximum)||minimum>=maximum)return;
    state.actors.forEach(actor=>{{const mapper=actor.getMapper(); if(mapper.setScalarRange)mapper.setScalarRange(minimum,maximum); const lut=mapper.getLookupTable&&mapper.getLookupTable(); if(lut&&lut.setMappingRange){{lut.setMappingRange(minimum,maximum); if(lut.updateRange)lut.updateRange();}}}}); state.rw.render();
  }}
  function visibility(kind, visible) {{
    const state=scene(); if(!state)return;
    const allRenderers=[state.rw,...state.rw.getChildRenderWindows()].flatMap(item=>item.getRenderers());
    if(kind==='axes') allRenderers.filter(renderer=>renderer!==state.renderer).forEach(renderer=>renderer.getViewProps().forEach(prop=>prop.setVisibility&&prop.setVisibility(visible)));
    if(kind==='scalar-bar') allRenderers.forEach(renderer=>renderer.getViewProps().filter(prop=>prop.isA&&prop.isA('vtkScalarBarActor')).forEach(prop=>prop.setVisibility(visible)));
    state.rw.render();
  }}
  async function probe(event) {{
    const state=scene(); if(!state)return; const rect=event.currentTarget.getBoundingClientRect(), size=state.view.getSize();
    const x=Math.round((event.clientX-rect.left)*size[0]/rect.width), y=Math.round((rect.bottom-event.clientY)*size[1]/rect.height);
    const selector=state.view.getSelector(); selector.setFieldAssociation(1); selector.attach(state.view,state.renderer);
    const nodes=await selector.selectAsync(state.renderer,x,y,x,y); if(!nodes.length)return;
    const properties=nodes[0].getProperties(), actor=properties.prop, id=properties.attributeID;
    if(!actor||id==null)return;
    const data=actor.getMapper().getInputData(); data.buildCells();
    const pointArray=data.getPointData().getArrayByName(metadata.scalarName);
    const cellArray=data.getCellData().getArrayByName(metadata.scalarName);
    let value=null;
    if(pointArray){{
      const cell=data.getCellPoints(id), pointIds=cell&&cell.cellPointIds ? Array.from(cell.cellPointIds) : [];
      const values=pointArray.getData(), components=pointArray.getNumberOfComponents()||1;
      if(pointIds.length)value=pointIds.reduce((sum,pointId)=>sum+values[pointId*components],0)/pointIds.length;
    }} else if(cellArray) {{
      value=cellArray.getData()[id*(cellArray.getNumberOfComponents()||1)];
    }}
    if(!Number.isFinite(value))return;
    window.parent.postMessage({{type:'phoenix-scalar-picked',value,scalarName:metadata.scalarName,scalarTitle:metadata.scalarTitle}},window.location.origin);
  }}
  function ready() {{
    const state=scene(), root=document.querySelector('#vtk-root'); if(!state||!root){{setTimeout(ready,100);return;}}
    let start=null; root.addEventListener('pointerdown',e=>start=[e.clientX,e.clientY]); root.addEventListener('pointerup',e=>{{if(start&&Math.hypot(e.clientX-start[0],e.clientY-start[1])<=4)probe(e).catch(()=>{{}});}});
    window.parent.postMessage({{type:'phoenix-scene-ready',...metadata}},window.location.origin);
  }}
  window.addEventListener('message',event=>{{if(event.origin!==window.location.origin)return; const d=event.data||{{}}; if(d.type==='phoenix-camera')camera(d.command); if(d.type==='phoenix-scalar-range')scalarRange(Number(d.minimum),Number(d.maximum)); if(d.type==='phoenix-visibility')visibility(d.target,Boolean(d.visible)); if(d.type==='phoenix-screenshot')Promise.resolve(scene()?.rw.captureImages()).then(images=>window.parent.postMessage({{type:'phoenix-screenshot-ready',image:images&&images[0]}},window.location.origin));}});
  ready();
}})();
</script>
"""
    html = path.read_text(encoding="utf-8")
    path.write_text(html.replace("</body>", script + "\n</body>"), encoding="utf-8")
