from pathlib import Path

import pytest

from phoenix_aero_lite.geometry.wing_reference import WingReferenceResult
from phoenix_aero_lite.models.geometry import (
    BoundingBox,
    GeometryInspection,
    SurfacePreviewArtifacts,
)
from phoenix_aero_lite.visualization.web_scene import InteractiveScene
from phoenix_aero_lite.web.model_service import LocalModelService, ModelState


def fake_preview(source: Path, output: Path) -> SurfacePreviewArtifacts:
    assert source.name == "model.step"
    output.write_text("real vtk", encoding="utf-8")
    return SurfacePreviewArtifacts(
        inspection=GeometryInspection(
            volume_count=1,
            surface_count=6,
            bounding_box=BoundingBox((0.0, 0.0, 0.0), (2.0, 0.4, 1.2)),
            unit="m",
            scale_note="official OCC target unit M",
        ),
        mesh_path=output.resolve(),
        point_count=8,
        cell_count=12,
        surface_tags=(10, 20),
        mesh_audit={
            "repair_applied": False,
            "engineering_analysis_blocked": False,
            "source_modified": False,
        },
    )


def fake_scene(source: Path, output: Path) -> InteractiveScene:
    assert source.read_text("utf-8") == "real vtk"
    output.write_text("<html>real scene</html>", encoding="utf-8")
    return InteractiveScene(output.resolve(), 8, 12, None, None, (10, 20))


def test_create_model_preserves_provenance_and_restores_snapshot(tmp_path: Path):
    root = tmp_path / "models"
    service = LocalModelService(root, preview_builder=fake_preview, scene_builder=fake_scene)

    snapshot = service.create("../../飞机.STEP", b"STEP DATA")

    assert snapshot.state is ModelState.READY
    assert snapshot.original_filename == "飞机.STEP"
    assert len(snapshot.source_sha256) == 64
    assert snapshot.inspection["dimensions_m"] == [2.0, 0.4, 1.2]
    assert snapshot.inspection["geometry_center_m"] == [1.0, 0.2, 0.6]
    assert snapshot.inspection["unit"] == "m"
    assert snapshot.preview_point_count == 8
    assert snapshot.parameters["span_m"]["source"] == "software_computed"
    assert snapshot.parameters["span_m"]["confidence"] == "medium"
    assert snapshot.parameters["s_ref_m2"]["confidence"] == "unresolved"
    assert snapshot.parameters["s_ref_m2"]["current_value"] == "unresolved"
    assert snapshot.parameters["s_ref_m2"]["confirmed"] is False
    assert set(snapshot.artifacts) == {"preview.html", "surface.vtk"}
    assert Path(snapshot.artifacts["preview.html"]).is_relative_to(snapshot.model_directory)
    assert (snapshot.model_directory / "input" / "model.step").read_bytes() == b"STEP DATA"
    assert snapshot.selectable_surface_tags == (10, 20)
    assert snapshot.mesh_audit["source_modified"] is False
    assert snapshot.parameters["span_axis"]["current_value"] == "+X"
    assert snapshot.parameters["up_axis"]["current_value"] == "+Y"
    assert snapshot.parameters["nose_axis"]["current_value"] == "-Z"
    assert snapshot.parameters["nose_axis"]["confidence"] == "unresolved"

    restored = LocalModelService(root, preview_builder=fake_preview, scene_builder=fake_scene)
    assert restored.get(snapshot.model_id).to_dict() == snapshot.to_dict()


def test_override_parameter_retains_original_and_marks_confirmation(tmp_path: Path):
    service = LocalModelService(
        tmp_path / "models", preview_builder=fake_preview, scene_builder=fake_scene
    )
    snapshot = service.create("air.step", b"STEP DATA")

    updated = service.override_parameter(snapshot.model_id, "s_ref_m2", 0.91)

    value = updated.parameters["s_ref_m2"]
    assert value["detected_value"] == "unresolved"
    assert value["current_value"] == 0.91
    assert value["source"] == "user_override"
    assert value["original_source"] == "software_default"
    assert value["overridden"] is True
    assert value["confirmed"] is True

    restored = service.restore_parameter(snapshot.model_id, "s_ref_m2")
    restored_value = restored.parameters["s_ref_m2"]
    assert restored_value["current_value"] == "unresolved"
    assert restored_value["source"] == "software_default"
    assert restored_value["overridden"] is False


def test_create_model_rejects_non_step_empty_and_oversized_content(tmp_path: Path):
    service = LocalModelService(
        tmp_path / "models", preview_builder=fake_preview, scene_builder=fake_scene
    )

    for filename, content, code in (
        ("air.txt", b"STEP", "MODEL_MUST_BE_STEP"),
        ("air.step", b"", "MODEL_EMPTY"),
    ):
        try:
            service.create(filename, content)
        except ValueError as error:
            assert str(error) == code
        else:
            raise AssertionError(f"{code} was not raised")


def test_batch_override_is_atomic_when_one_value_is_invalid(tmp_path: Path):
    service = LocalModelService(
        tmp_path / "models", preview_builder=fake_preview, scene_builder=fake_scene
    )
    model = service.create("air.step", b"STEP DATA")
    before = service.get(model.model_id)

    with pytest.raises(ValueError, match="MODEL_ORIENTATION_AXES_CONFLICT"):
        service.override_parameters(
            model.model_id,
            {"nose_axis": "+X", "up_axis": "+X", "s_ref_m2": 0.8},
        )

    assert service.get(model.model_id) == before


def test_real_surface_selection_recomputes_reference_and_keeps_override_history(
    tmp_path: Path,
):
    calls = []

    def calculate(mesh, tags, *, up_axis, span_axis):
        calls.append((mesh.name, tags, up_axis, span_axis))
        return WingReferenceResult(
            surface_tags=tags,
            s_ref_m2=0.84,
            c_ref_m=0.42,
            span_m=2.0,
            projected_positive_m2=0.84,
            projected_negative_m2=0.82,
            confidence="medium",
            rationale_zh="由真实 OCC 曲面投影计算",
        )

    service = LocalModelService(
        tmp_path / "models",
        preview_builder=fake_preview,
        scene_builder=fake_scene,
        wing_reference_calculator=calculate,
    )
    snapshot = service.create("air.step", b"STEP DATA")

    selected = service.select_wing_surfaces(snapshot.model_id, (20, 10, 20))

    assert calls == [("surface.vtk", (10, 20), "+Y", "+X")]
    assert selected.selected_surface_tags == (10, 20)
    assert selected.parameters["s_ref_m2"]["current_value"] == 0.84
    assert selected.parameters["c_ref_m"]["current_value"] == 0.42
    assert selected.parameters["span_m"]["current_value"] == 2.0
    assert selected.parameters["s_ref_m2"]["source"] == "software_computed"
    assert selected.parameters["s_ref_m2"]["confidence"] == "medium"

    overridden = service.override_parameter(snapshot.model_id, "s_ref_m2", 0.9)
    assert overridden.parameters["s_ref_m2"]["detected_value"] == 0.84
    assert overridden.parameters["s_ref_m2"]["current_value"] == 0.9
    assert overridden.parameters["s_ref_m2"]["source"] == "user_override"

    reset = service.select_wing_surfaces(snapshot.model_id, ())
    assert reset.selected_surface_tags == ()
    assert reset.wing_reference is None
