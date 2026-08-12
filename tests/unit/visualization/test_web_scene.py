from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import time

import numpy as np
import pyvista as pv
import pytest

from phoenix_aero_lite.visualization import web_scene
from phoenix_aero_lite.visualization.web_scene import (
    export_interactive_surface,
    export_pressure_surface,
    export_streamline_scene,
    export_velocity_slice,
)


def test_all_real_scene_exporters_share_one_process_lock():
    active = 0
    maximum_active = 0
    state_lock = Lock()

    def probe(name: str) -> str:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.04)
            return name
        finally:
            with state_lock:
                active -= 1

    first = web_scene._serialized_scene_export(probe)
    second = web_scene._serialized_scene_export(probe)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(first, "model-preview"),
                executor.submit(second, "job-result"),
            )
        )

    assert results == ("model-preview", "job-result")
    assert maximum_active == 1
    for exporter in (
        web_scene.export_interactive_surface,
        web_scene.export_pressure_surface,
        web_scene.export_y_plus_surface,
        web_scene.export_velocity_slice,
        web_scene.export_streamline_scene,
    ):
        assert hasattr(exporter, "__wrapped__")


def test_export_interactive_surface_is_standalone_and_uses_real_mesh(tmp_path: Path):
    source = tmp_path / "surface.vtp"
    output = tmp_path / "preview.html"
    pv.Cube().triangulate().save(source)

    result = export_interactive_surface(source, output)

    text = output.read_text(encoding="utf-8")
    assert result.output_path == output.resolve()
    assert result.point_count == 8
    assert result.cell_count == 12
    assert result.scalar_name is None
    assert output.stat().st_size > 100_000
    assert "<html" in text.casefold()
    assert str(source.resolve()) not in text
    assert "kitware.github.io/vtk-js/icon" not in text, "remote VTK.js favicon remained"


def test_export_interactive_surface_preserves_requested_scalar_and_title(tmp_path: Path):
    source = tmp_path / "surface.vtp"
    output = tmp_path / "cp.html"
    mesh = pv.Cube().triangulate()
    mesh.point_data["Pressure_Coefficient"] = list(range(mesh.n_points))
    mesh.save(source)

    result = export_interactive_surface(
        source,
        output,
        scalar_name="Pressure_Coefficient",
        scalar_title="Cp",
    )

    assert result.scalar_name == "Pressure_Coefficient"
    assert result.scalar_range == (0.0, 7.0)
    assert output.is_file()


def test_export_interactive_surface_embeds_real_vtkjs_surface_picker(tmp_path: Path):
    source = tmp_path / "tagged.vtk"
    output = tmp_path / "picker.html"
    mesh = pv.Cube().triangulate()
    mesh.cell_data["CellEntityIds"] = np.asarray([10] * 6 + [20] * 6)
    mesh.save(source)

    result = export_interactive_surface(source, output)

    html = output.read_text(encoding="utf-8")
    assert result.selectable_surface_tags == (10, 20)
    assert 'id="phoenix-surface-picker"' in html
    assert "selector.selectAsync(state.renderer" in html
    assert "phoenix-surface-selection" in html
    assert "phoenix-orientation-point" in html
    assert "phoenix-pick-mode" in html
    assert "data.getCellPoints(id)" in html
    assert "const surfaceTags = [10, 20]" in html


def test_export_pressure_surface_keeps_cp_and_pa_fields_distinct(tmp_path: Path):
    source = tmp_path / "surface.vtp"
    mesh = pv.Cube().triangulate()
    mesh.point_data["Pressure_Coefficient"] = list(range(mesh.n_points))
    mesh.point_data["Pressure"] = [101000.0 + value for value in range(mesh.n_points)]
    mesh.save(source)

    cp = export_pressure_surface(source, tmp_path / "cp.html", "cp")
    pressure = export_pressure_surface(source, tmp_path / "pressure.html", "pressure")

    assert cp.scalar_name == "Pressure_Coefficient"
    assert cp.scalar_range == (0.0, 7.0)
    assert pressure.scalar_name == "Pressure"
    assert pressure.scalar_range == (101000.0, 101007.0)

    picker_html = cp.output_path.read_text("utf-8")
    assert "setFieldAssociation(1)" in picker_html
    assert "data.buildCells()" in picker_html
    assert "data.getCellPoints(id)" in picker_html
    assert "phoenix-scalar-picked" in picker_html

    manual = export_pressure_surface(
        source, tmp_path / "manual.html", "cp", range_min=1.0, range_max=5.0
    )
    assert manual.scalar_range == (1.0, 5.0)
    assert 'id="phoenix-scene-controls"' in manual.output_path.read_text("utf-8")


def test_export_pressure_surface_rejects_unknown_mode_or_missing_real_field(tmp_path: Path):
    source = tmp_path / "surface.vtp"
    pv.Cube().save(source)

    for field, code in (("temperature", "PRESSURE_FIELD_INVALID"), ("cp", "WEB_SCENE_SCALAR_MISSING")):
        try:
            export_pressure_surface(source, tmp_path / f"{field}.html", field)
        except ValueError as error:
            assert str(error) == code
        else:
            raise AssertionError(f"{code} was not raised")


def test_export_y_plus_surface_uses_solver_field_and_stays_dimensionless(tmp_path: Path):
    source = tmp_path / "surface.vtp"
    mesh = pv.Cube().triangulate()
    mesh.point_data["Y_Plus"] = np.linspace(0.2, 3.7, mesh.n_points)
    mesh.save(source)

    scene = web_scene.export_y_plus_surface(source, tmp_path / "y-plus.html")

    assert scene.scalar_name == "Y_Plus"
    assert scene.scalar_range == pytest.approx((0.2, 3.7))
    html = scene.output_path.read_text("utf-8")
    assert '"scalarTitle": "Y+"' in html
    assert "Pressure (Pa)" not in html


def test_export_y_plus_surface_refuses_to_invent_a_missing_field(tmp_path: Path):
    source = tmp_path / "surface.vtp"
    pv.Cube().triangulate().save(source)

    with pytest.raises(ValueError, match="Y_PLUS_FIELD_MISSING"):
        web_scene.export_y_plus_surface(source, tmp_path / "y-plus.html")


@pytest.mark.parametrize(
    "values",
    [
        np.tile((1.0, 2.0, 3.0), (8, 1)),
        np.linspace(-0.2, 3.7, 8),
    ],
)
def test_export_y_plus_surface_rejects_non_scalar_or_negative_fields(
    tmp_path: Path, values
):
    source = tmp_path / "surface.vtp"
    mesh = pv.Cube().triangulate()
    mesh.point_data["Y_Plus"] = values
    mesh.save(source)

    with pytest.raises(ValueError, match="Y_PLUS_FIELD_INVALID"):
        web_scene.export_y_plus_surface(source, tmp_path / "y-plus.html")


def flow_grid() -> pv.UnstructuredGrid:
    image = pv.ImageData(dimensions=(10, 9, 8), spacing=(0.2, 0.2, 0.2))
    grid = image.cast_to_unstructured_grid()
    grid.point_data["Velocity"] = [[1.0, 0.0, 0.0]] * grid.n_points
    return grid


def test_velocity_slice_uses_real_velocity_magnitude_and_supported_presets(tmp_path: Path):
    source = tmp_path / "flow.vtu"
    flow_grid().save(source)

    scene = export_velocity_slice(
        source,
        tmp_path / "slice.html",
        "longitudinal",
        position=0.25,
        opacity=0.6,
    )

    assert scene.scalar_name == "Velocity_Magnitude"
    assert scene.scalar_range == (1.0, 1.0)
    assert scene.point_count > 0
    assert scene.cell_count > 0
    assert "phoenix-scalar-picked" in scene.output_path.read_text("utf-8")
    try:
        export_velocity_slice(source, tmp_path / "bad.html", "coordinates")
    except ValueError as error:
        assert str(error) == "VELOCITY_SLICE_PRESET_INVALID"
    else:
        raise AssertionError("VELOCITY_SLICE_PRESET_INVALID was not raised")


def test_streamline_seed_plane_is_upstream_perpendicular_and_bounded(tmp_path: Path):
    volume = tmp_path / "flow.vtu"
    surface = tmp_path / "surface.vtp"
    flow_grid().save(volume)
    pv.Cube(center=(0.9, 0.8, 0.7), x_length=0.4, y_length=0.5, z_length=0.3).save(surface)

    scene = export_streamline_scene(
        volume,
        surface,
        tmp_path / "streamlines.html",
        flow_direction=(1.0, 0.0, 0.0),
        density="sparse",
        line_width=2.0,
        opacity=0.7,
    )

    assert scene.scalar_name == "Velocity_Magnitude"
    assert scene.point_count > 0
    assert scene.cell_count > 0
    assert "phoenix-screenshot-ready" in scene.output_path.read_text("utf-8")
    try:
        export_streamline_scene(
            volume,
            surface,
            tmp_path / "dense-bad.html",
            flow_direction=(1.0, 0.0, 0.0),
            density="unbounded",
        )
    except ValueError as error:
        assert str(error) == "STREAMLINE_DENSITY_INVALID"
    else:
        raise AssertionError("STREAMLINE_DENSITY_INVALID was not raised")
