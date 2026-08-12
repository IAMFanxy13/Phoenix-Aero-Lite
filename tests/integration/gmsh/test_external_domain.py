"""Synthetic external-domain and bounded Preview mesh integration tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import gmsh
import meshio
import numpy as np
import pytest

from phoenix_aero_lite.meshing import gmsh_mesher
from phoenix_aero_lite.meshing.gmsh_mesher import GmshMesher
from phoenix_aero_lite.models.mesh import MeshingError
from phoenix_aero_lite.models.parameters import MeshMode, MeshParameters


def _preview(target: float = 1.0) -> MeshParameters:
    return MeshParameters(MeshMode.PREVIEW, target)


def test_preview_builds_tagged_external_mesh_and_supported_artifacts(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")

    artifacts = external_mesher().build_external_mesh(
        step_path, _preview(), tmp_path / "mesh"
    )

    assert artifacts.domain.reference_length_m == pytest.approx(2.0, abs=2e-6)
    assert artifacts.domain.aircraft_bounds_m.minimum_m == pytest.approx(
        (-1.0, -3.0, -0.2), abs=2e-6
    )
    assert artifacts.domain.aircraft_bounds_m.maximum_m == pytest.approx(
        (1.0, 3.0, 0.2), abs=2e-6
    )
    assert artifacts.domain.outer_bounds_m.minimum_m == pytest.approx(
        (-7.0, -11.0, -8.2), abs=3e-6
    )
    assert artifacts.domain.outer_bounds_m.maximum_m == pytest.approx(
        (17.0, 11.0, 8.2), abs=3e-6
    )
    assert {group.name for group in artifacts.physical_groups} == {
        "fluid",
        "aircraft",
        "farfield",
    }
    assert all(group.entity_count > 0 for group in artifacts.physical_groups)
    assert artifacts.strategy.near_wall_layers_present is False
    assert artifacts.strategy.drag_fidelity == "preview_only"
    assert artifacts.quality.node_count > 0
    assert artifacts.quality.cell_count > 0
    assert artifacts.quality.minimum_quality >= 0.0
    for path in (
        artifacts.msh_path,
        artifacts.su2_path,
        artifacts.vtu_path,
        artifacts.mapping_json_path,
        artifacts.quality_json_path,
    ):
        assert path.is_file()
        assert path.stat().st_size > 0

    mapping = json.loads(artifacts.mapping_json_path.read_text(encoding="utf-8"))
    assert mapping["coordinate_mapping"] == {
        "x": "-z_original",
        "y": "x_original",
        "z": "y_original",
    }
    assert "entity_tags" not in json.dumps(mapping)
    assert mapping["strategy"]["aircraft_size_min_m"] == pytest.approx(0.5)
    assert mapping["strategy"]["wake_size_m"] == pytest.approx(0.75)

    visualization = meshio.read(artifacts.vtu_path)
    assert len(visualization.points) == artifacts.quality.node_count
    assert sum(len(block.data) for block in visualization.cells) > 0
    assert not gmsh.isInitialized()


def test_preview_mesh_can_run_from_qt_worker_thread(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    """The GUI executes meshing in a QThreadPool worker."""

    step_path = synthetic_step_factory(tmp_path / "worker-wing.step")
    mesher = external_mesher()
    with ThreadPoolExecutor(max_workers=1) as executor:
        artifacts = executor.submit(
            mesher.build_external_mesh,
            step_path,
            _preview(3.0),
            tmp_path / "worker-mesh",
        ).result(timeout=60)

    assert artifacts.su2_path.is_file()
    assert artifacts.quality.node_count > 0
    assert not gmsh.isInitialized()


def test_explicit_validator_ignores_a_poisoned_path_binary(
    tmp_path: Path,
    synthetic_step_factory,
    official_su2_validator_path: Path,
    monkeypatch,
):
    path_directory = tmp_path / "path"
    path_directory.mkdir()
    shutil.copy2(sys.executable, path_directory / "SU2_CFD.exe")
    monkeypatch.setenv("PATH", str(path_directory))
    step_path = synthetic_step_factory(tmp_path / "wing.step")

    artifacts = GmshMesher(
        su2_validator_path=official_su2_validator_path
    ).build_external_mesh(step_path, _preview(3.0), tmp_path / "mesh")

    assert artifacts.quality.cell_count > 0
    assert artifacts.su2_path.is_file()


@pytest.mark.parametrize(
    ("kind", "scale", "code"),
    [
        ("curve_only", 1.0, "MODEL_STEP_NO_VOLUMES"),
        ("open_shell", 1.0, "MODEL_STEP_OPEN_SHELL"),
        ("two_wings", 1.0, "MODEL_STEP_MULTIPLE_VOLUMES"),
        ("zero_volume", 1.0, "MODEL_STEP_NON_POSITIVE_VOLUME"),
        ("wing", 1.0e-7, "MODEL_SCALE_OUT_OF_RANGE"),
        ("wing", 1.0e4, "MODEL_SCALE_OUT_OF_RANGE"),
    ],
)
def test_invalid_synthetic_geometry_has_stable_chinese_failure_and_reusable_gmsh(
    tmp_path: Path,
    synthetic_step_factory,
    external_mesher,
    kind: str,
    scale: float,
    code: str,
):
    step_path = synthetic_step_factory(tmp_path / f"{kind}.step", kind=kind, scale=scale)

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(), tmp_path / "mesh"
        )

    assert error.value.issue.code == code
    assert error.value.issue.text_zh
    assert not gmsh.isInitialized()

    valid_path = synthetic_step_factory(tmp_path / "valid.step")
    artifacts = external_mesher().build_external_mesh(
        valid_path, _preview(2.0), tmp_path / "valid"
    )
    assert artifacts.quality.cell_count > 0
    assert not gmsh.isInitialized()


def test_pre_generation_resource_ceiling_fails_without_final_artifacts_and_is_reusable(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")
    mesher = external_mesher(max_cells=1)

    with pytest.raises(MeshingError) as error:
        mesher.build_external_mesh(step_path, _preview(), tmp_path / "mesh")

    assert error.value.issue.code == "RESOURCE_CELL_LIMIT_EXCEEDED"
    assert not (tmp_path / "mesh" / "external_flow.msh").exists()
    assert not gmsh.isInitialized()


def test_post_generation_resource_ceiling_is_checked_before_final_artifacts(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")

    with pytest.raises(MeshingError) as error:
        external_mesher(max_nodes=500, max_cells=20_000).build_external_mesh(
            step_path, _preview(2.0), tmp_path / "mesh"
        )

    assert error.value.issue.code == "RESOURCE_NODE_LIMIT_EXCEEDED"
    assert not (tmp_path / "mesh" / "external_flow.msh").exists()
    assert not gmsh.isInitialized()


def test_conservative_preflight_rejects_before_mesh_generation(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")

    def forbidden_generate(_dimension: int) -> None:
        raise AssertionError("mesh generation must not run above the preflight ceiling")

    monkeypatch.setattr(gmsh.model.mesh, "generate", forbidden_generate)

    with pytest.raises(MeshingError) as error:
        external_mesher(max_cells=1_000).build_external_mesh(
            step_path, _preview(3.0), tmp_path / "mesh"
        )

    assert error.value.issue.code == "RESOURCE_CELL_LIMIT_EXCEEDED"
    assert not gmsh.isInitialized()


def test_immediate_generated_count_gate_precedes_quality_materialization(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")
    monkeypatch.setattr(gmsh_mesher, "_enforce_predicted_resources", lambda *_args: None)
    original_qualities = gmsh.model.mesh.getElementQualities

    def forbidden_quality_materialization(element_tags, quality_name="minSICN", *args):
        if quality_name == "minSICN":
            raise AssertionError("quality arrays must not be built above resource limits")
        return original_qualities(element_tags, quality_name, *args)

    monkeypatch.setattr(
        gmsh.model.mesh, "getElementQualities", forbidden_quality_materialization
    )

    with pytest.raises(MeshingError) as error:
        external_mesher(max_nodes=500).build_external_mesh(
            step_path, _preview(3.0), tmp_path / "mesh"
        )

    assert error.value.issue.code == "RESOURCE_NODE_LIMIT_EXCEEDED"
    assert not gmsh.isInitialized()


@pytest.mark.parametrize(
    ("filename", "contents", "code"),
    [
        ("missing.step", None, "MODEL_SOURCE_MISSING"),
        ("empty.step", b"", "MODEL_SOURCE_EMPTY"),
        ("invalid.step", b"not a STEP document", "MODEL_STEP_IMPORT_FAILED"),
    ],
)
def test_source_failures_have_stable_codes_and_leave_gmsh_reusable(
    tmp_path: Path,
    external_mesher,
    filename: str,
    contents: bytes | None,
    code: str,
):
    step_path = tmp_path / filename
    if contents is not None:
        step_path.write_bytes(contents)

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(), tmp_path / "mesh"
        )

    assert error.value.issue.code == code
    assert error.value.issue.text_zh
    assert not gmsh.isInitialized()


def test_preexisting_gmsh_session_model_and_options_are_restored(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")
    gmsh.initialize()
    try:
        gmsh.model.add("caller-owned")
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.option.setNumber("Mesh.MeshSizeMax", 123.0)
        original_models = tuple(gmsh.model.list())

        artifacts = external_mesher().build_external_mesh(
            step_path, _preview(2.0), tmp_path / "mesh"
        )

        assert artifacts.quality.cell_count > 0
        assert gmsh.isInitialized()
        assert tuple(gmsh.model.list()) == original_models
        assert gmsh.model.getCurrent() == "caller-owned"
        assert gmsh.option.getString("Geometry.OCCTargetUnit") == "MM"
        assert gmsh.option.getNumber("Mesh.MeshSizeMax") == pytest.approx(123.0)
    finally:
        gmsh.finalize()


def test_caller_owned_gmsh_session_is_restored_after_artifact_failure(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")
    gmsh.initialize()
    try:
        gmsh.model.add("caller-owned-failure")
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.option.setNumber("Mesh.MeshSizeMax", 321.0)
        original_models = tuple(gmsh.model.list())

        def fail_vtu_write(*_args, **_kwargs):
            raise OSError("injected VTU write failure")

        monkeypatch.setattr(meshio, "write", fail_vtu_write)
        with pytest.raises(MeshingError) as error:
            external_mesher().build_external_mesh(
                step_path, _preview(3.0), tmp_path / "mesh"
            )

        assert error.value.issue.code == "MESH_ARTIFACT_WRITE_FAILED"
        assert gmsh.isInitialized()
        assert tuple(gmsh.model.list()) == original_models
        assert gmsh.model.getCurrent() == "caller-owned-failure"
        assert gmsh.option.getString("Geometry.OCCTargetUnit") == "MM"
        assert gmsh.option.getNumber("Mesh.MeshSizeMax") == pytest.approx(321.0)
    finally:
        gmsh.finalize()


@pytest.mark.parametrize("mode", [MeshMode.STANDARD, MeshMode.FINE])
def test_standard_and_fine_use_verified_official_three_dimensional_layers(
    tmp_path: Path, synthetic_step_factory, external_mesher, mode: MeshMode
):
    step_path = synthetic_step_factory(tmp_path / f"{mode.value}.step")

    artifacts = external_mesher().build_external_mesh(
        step_path,
        MeshParameters(mode, 1.0),
        tmp_path / mode.value,
    )

    evidence = artifacts.quality.near_wall_evidence
    assert artifacts.strategy.near_wall_layers_present is True
    assert artifacts.strategy.drag_fidelity == "validated_near_wall_layers"
    assert evidence is not None
    assert evidence.api_path == "gmsh.model.geo.extrudeBoundaryLayer"
    assert evidence.gmsh_version == "4.15.2"
    assert evidence.validated_layer_count == artifacts.strategy.near_wall_layer_count
    assert evidence.measured_first_height_m == pytest.approx(
        artifacts.strategy.near_wall_first_height_m, rel=1e-8
    )
    assert evidence.measured_growth_ratio == pytest.approx(
        artifacts.strategy.near_wall_growth_ratio, rel=1e-8
    )
    assert evidence.measured_total_thickness_m == pytest.approx(
        artifacts.strategy.near_wall_total_thickness_m, rel=1e-8
    )
    assert evidence.layer_element_count == (
        evidence.source_face_count * artifacts.strategy.near_wall_layer_count
    )
    assert evidence.minimum_jacobian > 0.0
    assert evidence.minimum_volume > 0.0
    assert evidence.negative_jacobian_count == 0
    assert evidence.negative_volume_count == 0
    for group in artifacts.physical_groups:
        for bounds in group.bounding_boxes_m:
            assert all(
                math.isfinite(value)
                for value in (*bounds.minimum_m, *bounds.maximum_m)
            )
            assert all(
                minimum <= maximum
                for minimum, maximum in zip(
                    bounds.minimum_m, bounds.maximum_m, strict=True
                )
            )
            assert all(
                minimum >= outer_minimum - 1.0e-5
                and maximum <= outer_maximum + 1.0e-5
                for minimum, maximum, outer_minimum, outer_maximum in zip(
                    bounds.minimum_m,
                    bounds.maximum_m,
                    artifacts.domain.outer_bounds_m.minimum_m,
                    artifacts.domain.outer_bounds_m.maximum_m,
                    strict=True,
                )
            )
    assert any(
        name.startswith(("Prism", "Hexahedron"))
        for name, count in artifacts.quality.element_type_counts
        if count > 0
    )


def test_standard_persists_whole_hybrid_validity_and_face_incidence(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "standard-evidence.step")

    artifacts = external_mesher().build_external_mesh(
        step_path,
        MeshParameters(MeshMode.STANDARD, 2.0),
        tmp_path / "standard-evidence",
    )

    report = artifacts.quality.to_dict()
    validity = report.get("whole_mesh_validity")
    incidence = report.get("face_incidence")
    assert validity is not None
    assert validity["cell_count"] == artifacts.quality.cell_count
    assert validity["minimum_jacobian"] > 0.0
    assert validity["minimum_volume"] > 0.0
    assert validity["non_finite_jacobian_count"] == 0
    assert validity["non_finite_volume_count"] == 0
    assert validity["non_positive_jacobian_count"] == 0
    assert validity["non_positive_volume_count"] == 0
    assert incidence is not None
    assert incidence["external_face_count"] == (
        incidence["aircraft_face_count"] + incidence["farfield_face_count"]
    )
    assert incidence["unmarked_external_face_count"] == 0
    assert incidence["multiply_marked_external_face_count"] == 0
    assert incidence["tagged_internal_face_count"] == 0
    assert incidence["nonconformal_face_count"] == 0
    assert incidence["layer_interface_face_count"] > 0


@pytest.mark.parametrize(
    ("quality_name", "invalid_value"),
    [
        ("volume", -1.0),
        ("volume", math.nan),
        ("minDetJac", -1.0),
        ("minDetJac", math.nan),
    ],
)
def test_whole_mesh_rejects_nonpositive_or_nonfinite_signed_evidence(
    tmp_path: Path,
    synthetic_step_factory,
    external_mesher,
    monkeypatch,
    quality_name: str,
    invalid_value: float,
):
    step_path = synthetic_step_factory(tmp_path / "invalid-volume.step")
    original_qualities = gmsh.model.mesh.getElementQualities

    def invalid_signed_metric(element_tags, requested_quality="minSICN", *args):
        values = original_qualities(element_tags, requested_quality, *args)
        if requested_quality == quality_name and len(values):
            values = np.asarray(values, dtype=float).copy()
            values[0] = invalid_value
        return values

    monkeypatch.setattr(
        gmsh.model.mesh, "getElementQualities", invalid_signed_metric
    )

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(3.0), tmp_path / "invalid-volume"
        )

    assert error.value.issue.code == "NEGATIVE_ELEMENT_QUALITY"
    assert not gmsh.isInitialized()


def test_su2_semantic_round_trip_rejects_a_corrupted_marker_name(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "corrupt-su2.step")
    original_write = gmsh.write

    def corrupt_su2(path: str) -> None:
        original_write(path)
        candidate = Path(path)
        if candidate.suffix.lower() == ".su2":
            contents = candidate.read_text(encoding="utf-8")
            candidate.write_text(
                contents.replace(
                    "MARKER_TAG= aircraft", "MARKER_TAG= corrupted_aircraft"
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(gmsh, "write", corrupt_su2)

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(3.0), tmp_path / "corrupt-su2"
        )

    assert error.value.issue.code == "MESH_ARTIFACT_ROUNDTRIP_FAILED"


def test_vtu_round_trip_rejects_hybrid_cell_loss(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "lossy-vtu.step")
    original_write = meshio.write

    def lossy_vtu(path, mesh, *args, **kwargs):
        original_write(path, mesh, *args, **kwargs)
        candidate = Path(path)
        if candidate.suffix.lower() == ".vtu":
            restored = meshio.read(candidate)
            retained = [
                block for block in restored.cells if block.type not in {"wedge", "hexahedron"}
            ]
            assert len(retained) < len(restored.cells)
            original_write(
                candidate,
                meshio.Mesh(points=restored.points, cells=retained),
                file_format="vtu",
                binary=True,
            )

    monkeypatch.setattr(meshio, "write", lossy_vtu)

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path,
            MeshParameters(MeshMode.STANDARD, 2.0),
            tmp_path / "lossy-vtu",
        )

    assert error.value.issue.code == "MESH_ARTIFACT_ROUNDTRIP_FAILED"


def test_publication_replaces_stale_output_as_one_complete_set(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "stale.step")
    output = tmp_path / "mesh"
    output.mkdir()
    stale = output / "stale-from-prior-run.txt"
    stale.write_text("stale", encoding="utf-8")

    artifacts = external_mesher().build_external_mesh(
        step_path, _preview(3.0), output
    )

    assert not stale.exists()
    assert {path.name for path in output.iterdir()} == {
        artifacts.msh_path.name,
        artifacts.su2_path.name,
        artifacts.vtu_path.name,
        artifacts.mapping_json_path.name,
        artifacts.quality_json_path.name,
    }


def test_publication_rejects_a_hardlinked_leaf_without_touching_external_target(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "hardlink.step")
    output = tmp_path / "mesh"
    output.mkdir()
    outside = tmp_path / "outside.msh"
    outside.write_bytes(b"outside-original")
    os.link(outside, output / "external_flow.msh")

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(3.0), output
        )

    assert error.value.issue.code == "MESH_ARTIFACT_WRITE_FAILED"
    assert outside.read_bytes() == b"outside-original"


def test_publication_rejects_a_symlink_leaf_without_writing_outside(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "symlink.step")
    output = tmp_path / "mesh"
    output.mkdir()
    outside = tmp_path / "outside.msh"
    outside.write_bytes(b"outside-original")
    destination = output / "external_flow.msh"
    try:
        destination.symlink_to(outside)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        output.rmdir()
        outside_directory = tmp_path / "outside-directory"
        outside_directory.mkdir()
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(output), str(outside_directory)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert junction.returncode == 0, junction.stderr
        outside = outside_directory / "external_flow.msh"

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(3.0), output
        )

    assert error.value.issue.code == "MESH_ARTIFACT_WRITE_FAILED"
    if outside.exists():
        assert outside.read_bytes() == b"outside-original"


def test_publication_rolls_back_the_complete_previous_set_on_swap_failure(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "rollback.step")
    output = tmp_path / "mesh"
    output.mkdir()
    names = (
        "external_flow.msh",
        "external_flow.su2",
        "external_flow.vtu",
        "physical_groups.json",
        "mesh_quality.json",
    )
    for name in names:
        (output / name).write_bytes(f"old:{name}".encode())

    original_replace = Path.replace
    swap_attempts = 0

    def fail_new_set_swap(self: Path, target: Path):
        nonlocal swap_attempts
        target = Path(target)
        if target == output and ".stage-" in self.name:
            swap_attempts += 1
            raise OSError("injected atomic publication failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_new_set_swap)

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path, _preview(3.0), output
        )

    assert error.value.issue.code == "MESH_ARTIFACT_WRITE_FAILED"
    assert swap_attempts == 1
    assert {
        name: (output / name).read_bytes() for name in names
    } == {name: f"old:{name}".encode() for name in names}
    assert not list(tmp_path.glob(".mesh.stage-*"))
    assert not list(tmp_path.glob(".mesh.backup-*"))


def test_unvalidated_gmsh_version_keeps_standard_mode_gated(
    tmp_path: Path, synthetic_step_factory, external_mesher, monkeypatch
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")
    monkeypatch.setattr(gmsh, "__version__", "99.0.0")

    with pytest.raises(MeshingError) as error:
        external_mesher().build_external_mesh(
            step_path,
            MeshParameters(MeshMode.STANDARD, 1.0),
            tmp_path / "mesh",
        )

    assert error.value.issue.code == "NEAR_WALL_LAYER_NOT_VALIDATED"
    assert not gmsh.isInitialized()
