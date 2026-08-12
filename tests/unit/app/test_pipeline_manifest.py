from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from phoenix_aero_lite.app.pipeline import (
    _case_provenance,
    _pipeline_stage_fingerprints,
    _workflow_identity,
)
from phoenix_aero_lite.models.parameters import (
    AircraftParameters,
    CaseParameters,
    FlowParameters,
    MeshMode,
    MeshParameters,
    OutputParameters,
    ReferenceParameters,
    SolverParameters,
)


def test_pipeline_provenance_contains_reproducibility_inputs_without_raw_source_path(
    tmp_path: Path,
):
    source = tmp_path / "public.step"
    source.write_bytes(b"public fixture")
    su2 = tmp_path / "SU2_CFD.exe"
    su2.write_bytes(b"official binary fixture")
    parameters = CaseParameters(
        flow=FlowParameters(15.0, 1.225, 1.789e-5, 6.0),
        reference=ReferenceParameters(1.0, 0.5),
        aircraft=AircraftParameters(2.0),
        mesh=MeshParameters(MeshMode.PREVIEW, 0.2),
        solver=SolverParameters(100),
        output=OutputParameters(tmp_path / "case"),
    )

    result = _case_provenance(
        source=source,
        parameters=parameters,
        versions={"SU2": "8.5.0", "Gmsh": "4.15.2"},
        su2=su2,
    )

    assert result["source_sha256"]
    assert result["software_version"] == "0.1.0.dev0"
    assert result["git_commit"] == "unknown" or len(result["git_commit"]) == 40
    assert result["dependencies"]["Gmsh"] == "4.15.2"
    assert result["tools"]["SU2_CFD_sha256"]
    assert result["cache"]["schema_id"] == "phoenix-pipeline-cache-v2"
    assert result["cache"]["stage_implementations"]["mesh"]
    assert result["user_inputs"]["flow"]["velocity_m_s"] == 15.0
    assert "source_path" not in result


def test_stage_fingerprints_follow_physical_dependency_invalidation(tmp_path: Path):
    source = tmp_path / "public.step"
    source.write_bytes(b"public fixture")
    su2 = tmp_path / "SU2_CFD.exe"
    su2.write_bytes(b"official binary fixture")
    base = CaseParameters(
        flow=FlowParameters(15.0, 1.225, 1.789e-5, 6.0),
        reference=ReferenceParameters(1.0, 0.5),
        aircraft=AircraftParameters(2.0),
        mesh=MeshParameters(MeshMode.STANDARD, 0.2),
        solver=SolverParameters(800),
        output=OutputParameters(tmp_path / "case"),
    )
    versions = {"SU2": "8.5.0", "Gmsh": "4.15.2"}
    initial = _pipeline_stage_fingerprints(source, base, versions, su2)

    mass_only = _pipeline_stage_fingerprints(
        source,
        replace(base, aircraft=AircraftParameters(3.0)),
        versions,
        su2,
    )
    assert mass_only["stage"] == initial["stage"]
    assert mass_only["mesh"] == initial["mesh"]
    assert mass_only["config"] == initial["config"]
    assert mass_only["solve"] == initial["solve"]
    assert mass_only["visualize"] == initial["visualize"]
    assert mass_only["parse"] != initial["parse"]
    assert mass_only["report"] != initial["report"]

    flow_changed = _pipeline_stage_fingerprints(
        source,
        replace(base, flow=replace(base.flow, velocity_m_s=20.0)),
        versions,
        su2,
    )
    assert flow_changed["inspect"] == initial["inspect"]
    assert flow_changed["mesh"] != initial["mesh"]
    assert flow_changed["solve"] != initial["solve"]

    angle_changed = _pipeline_stage_fingerprints(
        source,
        replace(base, flow=replace(base.flow, angle_of_attack_deg=8.0)),
        versions,
        su2,
    )
    assert angle_changed["mesh"] == initial["mesh"]
    assert angle_changed["config"] != initial["config"]
    assert angle_changed["solve"] != initial["solve"]

    area_changed = _pipeline_stage_fingerprints(
        source,
        replace(base, reference=replace(base.reference, s_ref_m2=1.2)),
        versions,
        su2,
    )
    assert area_changed["mesh"] == initial["mesh"]
    assert area_changed["config"] != initial["config"]

    solver_changed = _pipeline_stage_fingerprints(
        source,
        replace(base, solver=SolverParameters(1200)),
        versions,
        su2,
    )
    assert solver_changed["mesh"] == initial["mesh"]
    assert solver_changed["config"] != initial["config"]


def test_cache_schema_and_per_stage_implementation_versions_invalidate_old_code(
    tmp_path: Path,
):
    source = tmp_path / "public.step"
    source.write_bytes(b"public fixture")
    su2 = tmp_path / "SU2_CFD.exe"
    su2.write_bytes(b"official binary fixture")
    parameters = CaseParameters(
        flow=FlowParameters(15.0, 1.225, 1.789e-5, 6.0),
        reference=ReferenceParameters(1.0, 0.5),
        aircraft=AircraftParameters(2.0),
        mesh=MeshParameters(MeshMode.STANDARD, 0.2),
        solver=SolverParameters(800),
        output=OutputParameters(tmp_path / "case"),
    )
    versions = {"SU2": "8.5.0", "Gmsh": "4.15.2"}
    implementation = {
        "stage": "stage-v1",
        "inspect": "inspect-v1",
        "mesh": "mesh-v1",
        "config": "config-v1",
        "solve": "solve-v1",
        "parse": "parse-v1",
        "visualize": "visualize-v1",
        "report": "report-v1",
    }
    initial = _pipeline_stage_fingerprints(
        source,
        parameters,
        versions,
        su2,
        implementation_versions=implementation,
    )
    changed = _pipeline_stage_fingerprints(
        source,
        parameters,
        versions,
        su2,
        implementation_versions={**implementation, "mesh": "mesh-v2"},
    )

    assert changed["stage"] == initial["stage"]
    assert changed["inspect"] == initial["inspect"]
    assert changed["mesh"] != initial["mesh"]
    assert changed["config"] != initial["config"]
    assert changed["solve"] != initial["solve"]
    assert changed["parse"] != initial["parse"]
    assert changed["visualize"] != initial["visualize"]
    assert changed["report"] != initial["report"]
    assert _workflow_identity(
        source, versions, su2, cache_schema_id="pipeline-cache-v1"
    ) != _workflow_identity(
        source, versions, su2, cache_schema_id="pipeline-cache-v2"
    )
