"""Real Gmsh/OpenCASCADE integration tests using synthetic STEP fixtures."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import gmsh
import pytest
import pyvista as pv

from phoenix_aero_lite.geometry.gmsh_geometry import (
    GeometryInspectionError,
    GmshGeometryAdapter,
)


def _write_occ_step(path: Path, *, solid: bool = True) -> None:
    """Write a synthetic 1 x 2 x 3 m shape from OCC's millimetre STEP frame."""

    gmsh.initialize()
    previous_target_unit = gmsh.option.getString("Geometry.OCCTargetUnit")
    try:
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.add(f"fixture-{uuid4().hex}")
        if solid:
            gmsh.model.occ.addBox(0.0, 0.0, 0.0, 1000.0, 2000.0, 3000.0)
        else:
            gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, 1000.0, 2000.0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.option.setString("Geometry.OCCTargetUnit", previous_target_unit)
        gmsh.finalize()


def test_inspect_step_returns_tag_free_metre_summary_for_occ_box(tmp_path: Path):
    assert not gmsh.isInitialized(), "previous workflow leaked a Gmsh session"
    step_path = tmp_path / "box.step"
    _write_occ_step(step_path)

    inspection = GmshGeometryAdapter().inspect_step(step_path)

    assert inspection.volume_count == 1
    assert inspection.surface_count == 6
    assert inspection.bounding_box_min_m == pytest.approx((0.0, 0.0, 0.0), abs=2e-7)
    assert inspection.bounding_box_max_m == pytest.approx((1.0, 2.0, 3.0), abs=2e-7)
    assert inspection.dimensions_m == pytest.approx((1.0, 2.0, 3.0), abs=4e-7)
    assert inspection.diagonal_m == pytest.approx(14.0**0.5, abs=4e-7)
    assert inspection.unit == "m"
    assert "OCCTargetUnit" in inspection.scale_note
    assert "M" in inspection.scale_note
    assert not hasattr(inspection, "entity_tags")
    assert not gmsh.isInitialized()


def test_build_surface_preview_uses_real_step_faces_and_bounded_mesh(tmp_path: Path):
    step_path = tmp_path / "box.step"
    preview_path = tmp_path / "preview.vtk"
    _write_occ_step(step_path)

    preview = GmshGeometryAdapter().build_surface_preview(step_path, preview_path)

    mesh = pv.read(preview.mesh_path)
    assert preview.inspection.volume_count == 1
    assert preview.inspection.surface_count == 6
    assert preview.mesh_path == preview_path.resolve()
    assert preview.point_count == mesh.n_points > 0
    assert preview.cell_count == mesh.n_cells > 0
    assert preview.point_count <= 250_000
    assert preview.cell_count <= 500_000
    assert preview.mesh_audit["engineering_analysis_blocked"] is False
    assert preview.mesh_audit["source_modified"] is False
    assert not gmsh.isInitialized()


def test_sequential_owned_sessions_finalize_and_leave_no_imported_models(tmp_path: Path):
    first_path = tmp_path / "first.step"
    second_path = tmp_path / "second.step"
    _write_occ_step(first_path)
    _write_occ_step(second_path)
    adapter = GmshGeometryAdapter()

    assert adapter.inspect_step(first_path).volume_count == 1
    assert not gmsh.isInitialized()
    assert adapter.inspect_step(second_path).surface_count == 6
    assert not gmsh.isInitialized()


def test_owned_inspection_restores_global_target_unit_after_finalize(tmp_path: Path):
    step_path = tmp_path / "box.step"
    _write_occ_step(step_path)
    gmsh.initialize()
    try:
        initial_target_unit = gmsh.option.getString("Geometry.OCCTargetUnit")
    finally:
        gmsh.finalize()

    GmshGeometryAdapter().inspect_step(step_path)

    gmsh.initialize()
    try:
        assert gmsh.option.getString("Geometry.OCCTargetUnit") == initial_target_unit
    finally:
        gmsh.finalize()


def test_owned_session_can_inspect_from_qt_worker_thread(tmp_path: Path):
    """Gmsh must not install Python signal handlers outside the main thread."""

    step_path = tmp_path / "worker-box.step"
    _write_occ_step(step_path)

    with ThreadPoolExecutor(max_workers=1) as executor:
        inspection = executor.submit(
            GmshGeometryAdapter().inspect_step, step_path
        ).result(timeout=20)

    assert inspection.volume_count == 1
    assert inspection.surface_count == 6
    assert not gmsh.isInitialized()


def test_preexisting_session_is_not_finalized_and_its_model_is_restored(tmp_path: Path):
    step_path = tmp_path / "box.step"
    _write_occ_step(step_path)
    gmsh.initialize()
    try:
        gmsh.model.add("caller-owned-model")
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        original_models = tuple(gmsh.model.list())
        original_current = gmsh.model.getCurrent()

        inspection = GmshGeometryAdapter().inspect_step(step_path)

        assert inspection.volume_count == 1
        assert gmsh.isInitialized()
        assert tuple(gmsh.model.list()) == original_models
        assert gmsh.model.getCurrent() == original_current
        assert gmsh.option.getString("Geometry.OCCTargetUnit") == "MM"
    finally:
        gmsh.finalize()


@pytest.mark.parametrize(
    ("filename", "contents", "code", "text_zh"),
    [
        (
            "missing.step",
            None,
            "MODEL_SOURCE_MISSING",
            "STEP 源文件不存在或不是常规文件。",
        ),
        ("empty.step", b"", "MODEL_SOURCE_EMPTY", "STEP 源文件不能为空。"),
        (
            "invalid.step",
            b"not a STEP document",
            "MODEL_STEP_IMPORT_FAILED",
            "Gmsh OpenCASCADE 无法导入 STEP 几何。",
        ),
    ],
)
def test_inspect_step_returns_stable_chinese_validation_issue_and_cleans_up(
    tmp_path: Path,
    filename: str,
    contents: bytes | None,
    code: str,
    text_zh: str,
):
    step_path = tmp_path / filename
    if contents is not None:
        step_path.write_bytes(contents)

    with pytest.raises(GeometryInspectionError) as error:
        GmshGeometryAdapter().inspect_step(step_path)

    assert error.value.issue.code == code
    assert error.value.issue.text_zh == text_zh
    assert error.value.issues == (error.value.issue,)
    assert not gmsh.isInitialized()


def test_surface_only_step_is_rejected_as_no_volume(tmp_path: Path):
    step_path = tmp_path / "surface-only.step"
    _write_occ_step(step_path, solid=False)

    with pytest.raises(GeometryInspectionError) as error:
        GmshGeometryAdapter().inspect_step(step_path)

    assert error.value.issue.code == "MODEL_STEP_NO_VOLUMES"
    assert error.value.issue.text_zh == "STEP 几何不包含可用的三维实体。"
    assert not gmsh.isInitialized()


def test_import_failure_removes_temporary_model_from_preexisting_session(tmp_path: Path):
    invalid_step = tmp_path / "invalid.step"
    invalid_step.write_bytes(b"not a STEP document")
    gmsh.initialize()
    try:
        gmsh.model.add("caller-owned-model")
        original_models = tuple(gmsh.model.list())

        with pytest.raises(GeometryInspectionError) as error:
            GmshGeometryAdapter().inspect_step(invalid_step)

        assert error.value.issue.code == "MODEL_STEP_IMPORT_FAILED"
        assert gmsh.isInitialized()
        assert tuple(gmsh.model.list()) == original_models
        assert gmsh.model.getCurrent() == "caller-owned-model"
    finally:
        gmsh.finalize()
