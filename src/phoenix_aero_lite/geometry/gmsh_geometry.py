"""Safe, tag-free STEP inspection through Gmsh's OpenCASCADE API."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
from threading import RLock
from typing import Iterator
from uuid import uuid4

import gmsh

from phoenix_aero_lite.models.errors import ValidationIssue
from phoenix_aero_lite.models.geometry import (
    BoundingBox,
    GeometryInspection,
    SurfacePreviewArtifacts,
)


_GEOMETRY_ISSUE_TEXT_ZH = {
    "MODEL_SOURCE_MISSING": "STEP 源文件不存在或不是常规文件。",
    "MODEL_SOURCE_EMPTY": "STEP 源文件不能为空。",
    "MODEL_STEP_NO_VOLUMES": "STEP 几何不包含可用的三维实体。",
    "MODEL_STEP_IMPORT_FAILED": "Gmsh OpenCASCADE 无法导入 STEP 几何。",
}
_OCC_TARGET_UNIT = "M"
_SCALE_NOTE = 'Geometry.OCCTargetUnit forced to "M"; all reported lengths are metres.'
_GMSH_LOCK = RLock()


class GeometryInspectionError(ValueError):
    """Stable validation failure at the Gmsh STEP inspection boundary."""

    def __init__(self, code: str) -> None:
        self.issue = ValidationIssue(code=code, text_zh=_GEOMETRY_ISSUE_TEXT_ZH[code])
        self.issues = (self.issue,)
        super().__init__(code)


class GmshGeometryAdapter:
    """Inspect STEP topology and scale without exposing transient Gmsh tags."""

    def inspect_step(self, step_path: Path) -> GeometryInspection:
        path = Path(step_path)
        if not path.is_file():
            raise GeometryInspectionError("MODEL_SOURCE_MISSING")
        if path.stat().st_size == 0:
            raise GeometryInspectionError("MODEL_SOURCE_EMPTY")

        with _inspection_model():
            try:
                gmsh.model.occ.importShapes(str(path))
                gmsh.model.occ.synchronize()
            except Exception as error:
                raise GeometryInspectionError("MODEL_STEP_IMPORT_FAILED") from error

            volumes = gmsh.model.getEntities(3)
            if not volumes:
                raise GeometryInspectionError("MODEL_STEP_NO_VOLUMES")
            surfaces = gmsh.model.getEntities(2)
            bounding_box = _combined_volume_bounds(volumes)
            return GeometryInspection(
                volume_count=len(volumes),
                surface_count=len(surfaces),
                bounding_box=bounding_box,
                unit="m",
                scale_note=_SCALE_NOTE,
            )

    def build_surface_preview(
        self, step_path: Path, output_path: Path
    ) -> SurfacePreviewArtifacts:
        """Mesh imported OCC faces with Gmsh and write a bounded VTK preview."""

        path = Path(step_path)
        if not path.is_file():
            raise GeometryInspectionError("MODEL_SOURCE_MISSING")
        if path.stat().st_size == 0:
            raise GeometryInspectionError("MODEL_SOURCE_EMPTY")
        destination = Path(output_path).resolve(strict=False)
        if destination.suffix.casefold() != ".vtk":
            raise ValueError("GEOMETRY_PREVIEW_MUST_BE_VTK")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.stem}-{uuid4().hex}.vtk")

        with _inspection_model():
            try:
                gmsh.model.occ.importShapes(str(path))
                gmsh.model.occ.synchronize()
            except Exception as error:
                raise GeometryInspectionError("MODEL_STEP_IMPORT_FAILED") from error

            volumes = gmsh.model.getEntities(3)
            if not volumes:
                raise GeometryInspectionError("MODEL_STEP_NO_VOLUMES")
            surfaces = gmsh.model.getEntities(2)
            # Gmsh's official VTK writer persists physical entity ids as
            # ``CellEntityIds``. One physical group per OCC face gives the
            # browser a stable, real surface identity for VTK.js picking.
            for _, surface_tag in surfaces:
                gmsh.model.addPhysicalGroup(2, [surface_tag], tag=surface_tag)
            bounding_box = _combined_volume_bounds(volumes)
            inspection = GeometryInspection(
                volume_count=len(volumes),
                surface_count=len(surfaces),
                bounding_box=bounding_box,
                unit="m",
                scale_note=_SCALE_NOTE,
            )
            target_size = max(inspection.diagonal_m / 40.0, 1e-6)
            points = gmsh.model.getEntities(0)
            if points:
                gmsh.model.mesh.setSize(points, target_size)
            initial_messages = _generate_surface_mesh_with_log()
            initial_invalid = _invalid_element_warnings(initial_messages)
            final_target_size = target_size
            messages = initial_messages
            repair_applied = False
            if initial_invalid:
                # Official Gmsh's Frontal-Delaunay surface mesher resolves the
                # example_model.STEP BSpline triangulation when the characteristic size is
                # reduced from diagonal/40 to diagonal/62.5. Clear only the
                # generated mesh; the imported OCC model and user file remain
                # untouched.
                repair_applied = True
                final_target_size = max(target_size * 0.64, 1e-6)
                gmsh.model.mesh.clear()
                if points:
                    gmsh.model.mesh.setSize(points, final_target_size)
                messages = _generate_surface_mesh_with_log()
            final_invalid = _invalid_element_warnings(messages)
            node_tags, _, _ = gmsh.model.mesh.getNodes()
            # Only 2D face groups are written to the tagged VTK preview; 1D
            # curve elements reported by ``getElements()`` are intentionally
            # excluded so the persisted count matches the browser dataset.
            _, element_tags, _ = gmsh.model.mesh.getElements(2)
            point_count = len(node_tags)
            cell_count = sum(len(tags) for tags in element_tags)
            if point_count <= 0 or cell_count <= 0:
                raise GeometryInspectionError("MODEL_STEP_IMPORT_FAILED")
            if point_count > 250_000 or cell_count > 500_000:
                raise ValueError("GEOMETRY_PREVIEW_RESOURCE_LIMIT")
            try:
                gmsh.write(str(temporary))
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

        return SurfacePreviewArtifacts(
            inspection=inspection,
            mesh_path=destination,
            point_count=point_count,
            cell_count=cell_count,
            warnings=tuple(
                message for message in messages if "warning" in message.casefold()
            ),
            surface_tags=tuple(tag for _, tag in surfaces),
            mesh_audit={
                "method": "Gmsh OpenCASCADE + official Frontal-Delaunay surface mesher",
                "initial_target_size_m": target_size,
                "final_target_size_m": final_target_size,
                "repair_applied": repair_applied,
                "initial_invalid_warnings": list(initial_invalid),
                "final_invalid_warnings": list(final_invalid),
                "engineering_analysis_blocked": bool(final_invalid),
                "source_modified": False,
            },
        )


def _generate_surface_mesh_with_log() -> tuple[str, ...]:
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.logger.start()
    try:
        gmsh.model.mesh.generate(2)
        return tuple(gmsh.logger.get())
    finally:
        gmsh.logger.stop()


def _invalid_element_warnings(messages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        message for message in messages if "remain invalid" in message.casefold()
    )


def _combined_volume_bounds(volumes: list[tuple[int, int]]) -> BoundingBox:
    boxes = [gmsh.model.occ.getBoundingBox(dim, tag) for dim, tag in volumes]
    minimum_m = tuple(min(box[index] for box in boxes) for index in range(3))
    maximum_m = tuple(max(box[index] for box in boxes) for index in range(3, 6))
    return BoundingBox(minimum_m=minimum_m, maximum_m=maximum_m)


@contextmanager
def _inspection_model() -> Iterator[None]:
    """Own only the session/model created here and restore caller-owned state."""

    with _GMSH_LOCK:
        owns_session = not bool(gmsh.isInitialized())
        previous_model = ""
        previous_target_unit = ""
        previous_surface_algorithm = 6.0
        model_name = f"phoenix-step-inspection-{uuid4().hex}"
        model_added = False
        try:
            if owns_session:
                gmsh.initialize(interruptible=False)
            previous_model = gmsh.model.getCurrent()
            previous_target_unit = gmsh.option.getString("Geometry.OCCTargetUnit")
            previous_surface_algorithm = gmsh.option.getNumber("Mesh.Algorithm")
            gmsh.option.setString("Geometry.OCCTargetUnit", _OCC_TARGET_UNIT)
            gmsh.model.add(model_name)
            model_added = True
            yield
        finally:
            if gmsh.isInitialized():
                try:
                    if model_added and model_name in gmsh.model.list():
                        gmsh.model.setCurrent(model_name)
                        gmsh.model.remove()
                finally:
                    try:
                        gmsh.option.setString(
                            "Geometry.OCCTargetUnit", previous_target_unit
                        )
                        gmsh.option.setNumber(
                            "Mesh.Algorithm", previous_surface_algorithm
                        )
                        if previous_model and previous_model in gmsh.model.list():
                            gmsh.model.setCurrent(previous_model)
                    finally:
                        if owns_session:
                            gmsh.finalize()
