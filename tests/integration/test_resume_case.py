from __future__ import annotations

import json
from pathlib import Path

from phoenix_aero_lite.app.workflow import (
    ResumableWorkflow,
    StepOutcome,
    WorkflowStepDefinition,
)
from phoenix_aero_lite.models.case_manifest import CaseManifest


def test_manifest_is_atomic_strict_json_and_contains_artifact_hashes(tmp_path: Path):
    artifact = tmp_path / "artifact.bin"

    def execute(_context):
        artifact.write_bytes(b"evidence")
        return StepOutcome((artifact,), {"exit_code": 0})

    case = tmp_path / "case"
    ResumableWorkflow(
        case, (WorkflowStepDefinition("solve", (), execute),)
    ).run("d" * 64)
    payload = json.loads((case / "case_manifest.json").read_text(encoding="utf-8"))
    record = payload["steps"]["solve"]
    assert record["status"] == "complete"
    assert record["artifacts"][0]["sha256"]
    assert record["metadata"]["exit_code"] == 0
    assert not list(case.glob("*.tmp-*"))


def test_manifest_persists_auditable_case_provenance(tmp_path: Path):
    artifact = tmp_path / "artifact.bin"

    def execute(_context):
        artifact.write_bytes(b"evidence")
        return StepOutcome((artifact,), {})

    provenance = {
        "source_sha256": "a" * 64,
        "derived_sha256": {"staged_step": "b" * 64},
        "software_version": "0.1.0.dev0",
        "git_commit": "c" * 40,
        "os": "Windows-11",
        "python_version": "3.12.10",
        "dependencies": {"gmsh": "4.15.2"},
        "tools": {"SU2": "8.5.0"},
        "user_inputs": {"velocity_m_s": 15.0},
        "automatic_values": {"span_m": 2.0},
        "user_overrides": {"span_m": 2.1},
        "parameter_sources": {"span_m": "user_surface_selection"},
        "parent_task_id": None,
        "cache_source": None,
    }
    case = tmp_path / "case"

    ResumableWorkflow(
        case, (WorkflowStepDefinition("solve", (), execute),)
    ).run("e" * 64, provenance=provenance)

    payload = json.loads((case / "case_manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 4
    assert payload["provenance"] == provenance


def test_legacy_schema_one_loads_conservatively_and_upgrades_on_save(tmp_path: Path):
    path = tmp_path / "case_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fingerprint": "f" * 64,
                "steps": {},
            }
        ),
        encoding="utf-8",
    )

    manifest = CaseManifest.load_or_new(path, "f" * 64)

    assert manifest.schema_version == 4
    assert manifest.provenance == {}
    manifest.save_atomic(path)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 4
