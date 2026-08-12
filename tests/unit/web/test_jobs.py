import json
import hashlib
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from phoenix_aero_lite.models.parameters import MeshMode
from phoenix_aero_lite.models.evidence import (
    ConvergenceStatus as EvidenceConvergenceStatus,
    EvidenceStatus,
    ExecutionStatus,
    ScientificUseLevel,
)
from phoenix_aero_lite.solver.convergence import ConvergenceStatus
from phoenix_aero_lite.web.jobs import JobSnapshot, JobState, LocalJobService
from phoenix_aero_lite.web.models import JobRequest
from phoenix_aero_lite.visualization.web_scene import InteractiveScene


def request(mode=MeshMode.PREVIEW):
    return JobRequest(
        velocity_m_s=15.0,
        angle_of_attack_deg=6.0,
        s_ref_m2=1.0,
        c_ref_m=0.4,
        mass_kg=2.0,
        density_kg_m3=1.225,
        dynamic_viscosity_pa_s=1.7894e-5,
        mesh_mode=mode,
        target_cell_size_m=0.5,
        max_iterations=100,
    )


def completed_result(
    case_root: Path,
    status=ConvergenceStatus.STAGNATED,
    *,
    reused_steps=(),
    executed_steps=("stage", "mesh", "solve", "report"),
    stage_sources=None,
):
    artifacts = []
    for name in ("history.csv", "flow.vtu", "surface_flow.vtu", "report.html"):
        path = case_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("real artifact", encoding="utf-8")
        artifacts.append(path)
    convergence = SimpleNamespace(
        status=status,
        reason_code="RESIDUAL_STAGNATION",
        final_cl=0.55,
        final_cd=0.06,
    )
    stdout = case_root / "stdout.txt"
    stderr = case_root / "stderr.txt"
    stdout.write_text("SU2 output", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    artifacts.extend((stdout, stderr))
    write_result_manifest(case_root, artifacts, stage_sources=stage_sources)
    return SimpleNamespace(
        case_root=case_root,
        fingerprint="a" * 64,
        reused_steps=tuple(reused_steps),
        executed_steps=tuple(executed_steps),
        stage_sources=dict(stage_sources or {}),
        manifest_path=case_root / "case_manifest.json",
        context={
            "convergence": convergence,
            "mesh_quality": {
                "node_count": 14576,
                "cell_count": 14336,
                "negative_quality_count": 0,
                "non_manifold_face_count": 0,
                "near_wall": {
                    "required": False,
                    "present": False,
                    "drag_fidelity": "preview_only",
                },
            },
            "history_path": case_root / "history.csv",
            "flow_vtu": case_root / "flow.vtu",
            "surface_flow_vtu": case_root / "surface_flow.vtu",
            "report_path": case_root / "report.html",
            "process_result": SimpleNamespace(
                stdout_path=stdout,
                stderr_path=stderr,
            ),
        },
    )


def write_result_manifest(case_root, artifacts, *, stage_sources=None):
    records = []
    for path in artifacts:
        content = Path(path).read_bytes()
        records.append(
            {
                "path": str(Path(path).resolve()),
                "sha256": hashlib.sha256(content).hexdigest().upper(),
                "size": len(content),
            }
        )
    sources = dict(stage_sources or {})
    (case_root / "case_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fingerprint": "a" * 64,
                "provenance": {},
                "steps": {
                    "result": {
                        "status": "complete",
                        "artifacts": records,
                        "metadata": {},
                        "input_fingerprint": "b" * 64,
                        "producer_id": sources.get("result"),
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_shared_pipeline_cache_is_materialized_and_audited_per_job(tmp_path):
    shared = tmp_path / "pipeline-cache"
    calls = 0

    def runner(_source, _parameters, _case_root, _token):
        nonlocal calls
        calls += 1
        shared.mkdir(parents=True, exist_ok=True)
        return completed_result(
            shared,
            reused_steps=("stage", "inspect", "mesh") if calls == 2 else (),
            executed_steps=("config", "solve", "parse", "visualize", "report")
            if calls == 2
            else ("stage", "inspect", "mesh", "config", "solve", "parse", "visualize", "report"),
            stage_sources=(
                {
                    "stage": "manifest-producer",
                    "inspect": "manifest-producer",
                    "mesh": "manifest-producer",
                }
                if calls == 2
                else {}
            ),
        )

    service = LocalJobService(
        tmp_path / "jobs",
        runner=runner,
        cache_policy={
            "max_bytes": 20 * 1024**3,
            "cleanup_policy": "oldest-run-first",
        },
    )
    first = wait_terminal(
        service, service.submit("air.step", b"SAME STEP", request()).job_id
    )
    second = wait_terminal(
        service, service.submit("air.step", b"SAME STEP", request()).job_id
    )

    assert first.cache["reused_steps"] == []
    assert second.cache["reused_steps"] == ["stage", "inspect", "mesh"]
    assert second.cache["source_job_id"] == "manifest-producer"
    assert second.cache["source_job_ids"] == {
        "stage": "manifest-producer",
        "inspect": "manifest-producer",
        "mesh": "manifest-producer",
    }
    assert second.cache["fingerprint"] == "a" * 64
    assert second.cache["hash_validation"] is True
    assert second.cache["max_bytes"] == 20 * 1024**3
    assert Path(second.artifacts["case_manifest.json"]).is_file()
    for name in ("history.csv", "flow.vtu", "surface_flow.vtu", "report.html"):
        materialized = Path(second.artifacts[name])
        assert materialized.is_relative_to(second.job_directory)
        assert materialized.read_text(encoding="utf-8") == "real artifact"
    service.shutdown()
    restored = LocalJobService(tmp_path / "jobs", runner=runner)
    assert restored.get(second.job_id).cache["source_job_id"] == "manifest-producer"
    restored.shutdown()


def test_missing_required_result_artifact_fails_before_publication(tmp_path):
    def runner(_source, _parameters, case_root, _token):
        result = completed_result(case_root)
        Path(result.context["surface_flow_vtu"]).unlink()
        return result

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    final = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )

    assert final.state is JobState.FAILED
    assert final.error_code == "CACHE_ARTIFACT_SET_INCOMPLETE"
    assert not final.cache
    assert not (final.job_directory / "results").exists()


def test_tampered_manifest_artifact_fails_hash_validation_atomically(tmp_path):
    def runner(_source, _parameters, case_root, _token):
        result = completed_result(case_root)
        Path(result.context["flow_vtu"]).write_text("tampered", encoding="utf-8")
        return result

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    final = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )

    assert final.state is JobState.FAILED
    assert final.error_code == "CACHE_ARTIFACT_HASH_MISMATCH"
    assert not final.cache
    assert not (final.job_directory / "results").exists()


def test_missing_manifest_has_a_stable_failure_code(tmp_path):
    def runner(_source, _parameters, case_root, _token):
        result = completed_result(case_root)
        Path(result.manifest_path).unlink()
        return result

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    final = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )

    assert final.state is JobState.FAILED
    assert final.error_code == "CACHE_MANIFEST_INVALID"
    assert not (final.job_directory / "results").exists()


def test_cache_cleanup_runs_only_after_verified_job_artifacts_are_materialized(tmp_path):
    cleanup_observations = []

    def cleanup():
        job_directories = [path for path in (tmp_path / "jobs").iterdir() if path.is_dir()]
        cleanup_observations.append(
            len(job_directories) == 1
            and (job_directories[0] / "results" / "history.csv").is_file()
        )
        return {"bytes_after": 0, "limit_satisfied": True, "removed_runs": ["old"]}

    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
        cache_cleanup=cleanup,
    )
    final = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )

    assert final.state is JobState.COMPLETED
    assert cleanup_observations == [True]
    assert final.cache["post_materialization_cleanup"]["limit_satisfied"] is True
    assert final.cache["cache_entry_retained"] is True


def test_pipeline_cache_lease_is_released_before_post_materialization_cleanup(tmp_path):
    class Lease:
        released = False

        def release(self):
            self.released = True

    lease = Lease()

    def runner(_source, _parameters, case_root, _token):
        result = completed_result(case_root)
        result.cache_lease = lease
        return result

    def cleanup():
        assert lease.released is True
        return {"bytes_after": 0, "limit_satisfied": True, "removed_runs": []}

    service = LocalJobService(
        tmp_path / "jobs",
        runner=runner,
        cache_cleanup=cleanup,
    )
    final = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )

    assert final.state is JobState.COMPLETED
    assert lease.released is True


def wait_terminal(service, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = service.get(job_id)
        if snapshot.state.is_terminal:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_legacy_job_json_is_restored_with_conservative_missing_evidence(tmp_path):
    legacy_payload = {
        "job_id": "legacy-job",
        "state": "completed",
        "stage": "completed",
        "progress": 100,
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:01:00+00:00",
        "job_directory": str(tmp_path / "legacy-job"),
        "original_filename": "air.step",
        "request": {},
        "credibility": "reliable",
        "coefficients_usable": True,
        "convergence_status": "converged",
        "cl": 0.5,
        "cd": 0.05,
        "artifacts": {},
    }

    restored = JobSnapshot.from_dict(legacy_payload)

    assert restored.scientific_evidence.execution_status is ExecutionStatus.COMPLETED
    assert (
        restored.scientific_evidence.convergence_status
        is EvidenceConvergenceStatus.NOT_EVALUATED
    )
    assert (
        restored.scientific_evidence.scientific_use_level
        is ScientificUseLevel.INVALID
    )
    assert restored.scientific_evidence.validation_level is None
    assert restored.scientific_evidence.quantities == {}
    assert restored.coefficients_usable is False
    serialized = restored.to_dict()
    assert serialized["schema_version"] == 2
    assert serialized["execution_status"] == "completed"
    assert serialized["scientific_use_level"] == "invalid"
    assert serialized["quantity_evidence"] == {}


def pressure_scene(
    source: Path, output: Path, field: str, **_options
) -> InteractiveScene:
    assert source.name == "surface_flow.vtu"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"<html>{field}</html>", encoding="utf-8")
    scalar = "Pressure_Coefficient" if field == "cp" else "Pressure"
    return InteractiveScene(output.resolve(), 8, 12, scalar, (-1.0, 1.0))


def y_plus_scene(source: Path, output: Path, **_options) -> InteractiveScene:
    assert source.name == "surface_flow.vtu"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("<html>real Y+</html>", encoding="utf-8")
    return InteractiveScene(output.resolve(), 8, 12, "Y_Plus", (0.2, 3.7))


def velocity_scene(
    source: Path, output: Path, preset: str, **_options
) -> InteractiveScene:
    assert source.name == "flow.vtu"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"<html>{preset}</html>", encoding="utf-8")
    return InteractiveScene(output.resolve(), 8, 12, "Velocity_Magnitude", (0.0, 15.0))


def streamline_scene(
    volume: Path,
    surface: Path,
    output: Path,
    *,
    flow_direction: tuple[float, float, float],
    density: str,
    **_options,
) -> InteractiveScene:
    assert volume.name == "flow.vtu"
    assert surface.name == "surface_flow.vtu"
    assert flow_direction[0] > 0
    assert flow_direction[2] > 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"<html>{density}</html>", encoding="utf-8")
    return InteractiveScene(output.resolve(), 20, 5, "Velocity_Magnitude", (0.0, 15.0))


def test_submit_isolates_input_and_persists_caution_result(tmp_path):
    observed = {}

    def runner(source, parameters, case_root, cancellation):
        observed.update(source=source, parameters=parameters, case_root=case_root)
        return completed_result(case_root)

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    submitted = service.submit("../../飞机.STEP", b"STEP DATA", request())
    final = wait_terminal(service, submitted.job_id)

    assert final.state is JobState.COMPLETED
    assert final.credibility == "caution"
    assert final.coefficients_usable is False
    assert final.scientific_evidence.convergence_status is ConvergenceStatus.STAGNATED
    assert final.scientific_evidence.quantities["CL"].usable_for_diagnostic is True
    assert final.scientific_evidence.quantities["CL"].usable_for_engineering is False
    assert observed["source"].name == "model.step"
    assert observed["source"].read_bytes() == b"STEP DATA"
    assert observed["source"].is_relative_to(tmp_path / "jobs")
    assert observed["parameters"].mesh.mode is MeshMode.PREVIEW
    assert set(final.artifacts) == {
        "history.csv",
        "flow.vtu",
        "surface_flow.vtu",
        "report.html",
        "solver_stdout.txt",
        "solver_stderr.txt",
        "case_manifest.json",
    }
    persisted = json.loads((final.job_directory / "job.json").read_text("utf-8"))
    assert persisted["credibility"] == "caution"
    assert persisted["schema_version"] == 2
    assert persisted["scientific_evidence"]["convergence_status"] == "stagnated"
    assert persisted["quantity_evidence"]["y_plus"]["evidence_status"] == "missing"
    assert persisted["mesh_node_count"] == 14576
    assert persisted["mesh_cell_count"] == 14336
    assert persisted["elapsed_seconds"] >= 0.0

    restored = JobSnapshot.from_dict(persisted)
    assert restored.mesh_node_count == 14576
    assert restored.mesh_cell_count == 14336
    assert restored.elapsed_seconds == pytest.approx(persisted["elapsed_seconds"])


def test_runner_failure_is_a_failed_job_with_stable_error(tmp_path):
    def runner(*_args):
        raise RuntimeError("PIPELINE_GEOMETRY_INVALID")

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)

    assert final.state is JobState.FAILED
    assert final.error_code == "PIPELINE_GEOMETRY_INVALID"
    assert final.credibility == "invalid"
    assert (
        final.scientific_evidence.convergence_status
        is EvidenceConvergenceStatus.NOT_EVALUATED
    )


def test_solver_timeout_is_failed_execution_but_incomplete_convergence(tmp_path):
    def runner(*_args):
        raise RuntimeError("PIPELINE_SOLVE_TIMED_OUT")

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)

    assert final.state is JobState.FAILED
    assert final.scientific_evidence.execution_status is ExecutionStatus.FAILED
    assert (
        final.scientific_evidence.convergence_status
        is EvidenceConvergenceStatus.INCOMPLETE
    )


def test_progress_aware_runner_publishes_real_pipeline_stage(tmp_path):
    observed = []
    ready = threading.Event()

    def runner(source, parameters, case_root, cancellation, progress_callback):
        assert ready.wait(1)
        progress_callback("mesh", 35)
        observed.append(service.get(job_id).stage)
        progress_callback("solve", 65)
        observed.append(service.get(job_id).progress)
        return completed_result(case_root)

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    submitted = service.submit("air.step", b"STEP", request())
    job_id = submitted.job_id
    ready.set()
    final = wait_terminal(service, job_id)

    assert observed == ["mesh", 65]
    assert final.state is JobState.COMPLETED


def test_cancel_running_job_uses_shared_cancellation_token(tmp_path):
    started = threading.Event()

    def runner(_source, _parameters, _case_root, cancellation):
        started.set()
        while not cancellation.is_cancelled:
            time.sleep(0.01)
        raise RuntimeError("PIPELINE_SOLVE_CANCELLED")

    service = LocalJobService(tmp_path / "jobs", runner=runner)
    submitted = service.submit("air.step", b"STEP", request())
    assert started.wait(1)
    cancelled = service.cancel(submitted.job_id)
    final = wait_terminal(service, submitted.job_id)

    assert cancelled is True
    assert final.state is JobState.CANCELLED
    assert final.credibility == "invalid"
    assert final.scientific_evidence.execution_status is ExecutionStatus.CANCELLED
    assert (
        final.scientific_evidence.convergence_status
        is EvidenceConvergenceStatus.INCOMPLETE
    )


def test_service_restores_persisted_history(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)
    service.shutdown()

    restored = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)

    assert restored.get(final.job_id).state is JobState.COMPLETED
    assert [item.job_id for item in restored.list()] == [final.job_id]


def test_conservative_retry_creates_one_new_job_and_preserves_audit(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
    )
    original = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )

    retried = service.retry_conservative(original.job_id)
    final = wait_terminal(service, retried.job_id)

    assert final.job_id != original.job_id
    assert final.parent_job_id == original.job_id
    assert final.retry_attempt == 1
    assert final.request["max_iterations"] == 300
    assert final.automatic_changes["max_iterations"]["old"] == 100
    assert service.get(original.job_id) == original
    with pytest.raises(ValueError, match="JOB_CONSERVATIVE_RETRY_ALREADY_USED"):
        service.retry_conservative(original.job_id)


def test_near_wall_retry_switches_preview_to_fine_once(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
    )
    original = wait_terminal(
        service, service.submit("air.step", b"STEP", request()).job_id
    )
    updated = replace(
        original,
        credibility_reason_codes=("NEAR_WALL_LAYER_NOT_VALIDATED",),
    )
    service._publish(updated)

    retried = service.retry_conservative(original.job_id)

    assert retried.request["mesh_mode"] == "fine"
    assert retried.automatic_changes["mesh_mode"]["old"] == "preview"


def test_build_pressure_scene_is_task_scoped_registered_and_persistent(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
        pressure_scene_builder=pressure_scene,
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)

    scene = service.build_pressure_scene(final.job_id, "cp")

    path = Path(scene.artifacts["pressure_cp.html"])
    assert path.is_file()
    assert path.is_relative_to(final.job_directory)
    assert "cp" in path.read_text("utf-8")
    restored = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)
    assert restored.get(final.job_id).artifacts["pressure_cp.html"] == str(path)


def _publish_y_plus_evidence(
    service: LocalJobService,
    snapshot: JobSnapshot,
    status: EvidenceStatus,
    *,
    usable_for_diagnostic: bool = True,
) -> JobSnapshot:
    original = snapshot.scientific_evidence.quantities["y_plus"]
    has_value = status in {
        EvidenceStatus.ESTIMATED,
        EvidenceStatus.COMPUTED,
        EvidenceStatus.MEASURED,
        EvidenceStatus.VERIFIED,
    }
    quantity = replace(
        original,
        value=1.1 if has_value else None,
        evidence_status=status,
        usable_for_diagnostic=usable_for_diagnostic if has_value else False,
        source="solved wall field" if has_value else original.source,
        calculation_method="SU2 wall Y+" if has_value else original.calculation_method,
    )
    updated = replace(
        snapshot,
        scientific_evidence=replace(
            snapshot.scientific_evidence,
            quantities={
                **snapshot.scientific_evidence.quantities,
                "y_plus": quantity,
            },
        ),
    )
    service._publish(updated)
    return updated


@pytest.mark.parametrize(
    "status",
    [EvidenceStatus.COMPUTED, EvidenceStatus.MEASURED, EvidenceStatus.VERIFIED],
)
def test_build_y_plus_scene_is_task_scoped_and_uses_surface_result(
    tmp_path, status
):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
        y_plus_scene_builder=y_plus_scene,
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)
    final = _publish_y_plus_evidence(service, final, status)

    scene = service.build_y_plus_scene(final.job_id)

    path = Path(scene.artifacts["y_plus.html"])
    assert path.is_file()
    assert path.is_relative_to(final.job_directory)
    assert "real Y+" in path.read_text("utf-8")


@pytest.mark.parametrize(
    "status",
    [EvidenceStatus.MISSING, EvidenceStatus.ESTIMATED, EvidenceStatus.INVALID],
)
def test_build_y_plus_scene_rejects_unresolved_or_non_solver_evidence(
    tmp_path, status
):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
        y_plus_scene_builder=y_plus_scene,
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)
    final = _publish_y_plus_evidence(service, final, status)

    with pytest.raises(ValueError, match="Y_PLUS_EVIDENCE_UNAVAILABLE"):
        service.build_y_plus_scene(final.job_id)


def test_build_y_plus_scene_requires_diagnostic_permission(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
        y_plus_scene_builder=y_plus_scene,
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)
    final = _publish_y_plus_evidence(
        service,
        final,
        EvidenceStatus.COMPUTED,
        usable_for_diagnostic=False,
    )

    with pytest.raises(ValueError, match="Y_PLUS_EVIDENCE_UNAVAILABLE"):
        service.build_y_plus_scene(final.job_id)


def test_restore_migrates_legacy_job_when_surface_is_sibling_of_flow(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)
    service.shutdown()
    record_path = final.job_directory / "job.json"
    record = json.loads(record_path.read_text("utf-8"))
    record["artifacts"].pop("surface_flow.vtu")
    record_path.write_text(json.dumps(record), encoding="utf-8")

    restored = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)

    surface = Path(restored.get(final.job_id).artifacts["surface_flow.vtu"])
    assert surface.name == "surface_flow.vtu"
    assert surface.is_file()


def test_build_velocity_and_streamline_scenes_register_task_scoped_artifacts(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: completed_result(case_root),
        velocity_scene_builder=velocity_scene,
        streamline_scene_builder=streamline_scene,
    )
    final = wait_terminal(service, service.submit("air.step", b"STEP", request()).job_id)

    sliced = service.build_velocity_scene(final.job_id, "wing")
    streamed = service.build_streamline_scene(final.job_id, "sparse")

    assert Path(sliced.artifacts["velocity_wing.html"]).is_file()
    assert Path(streamed.artifacts["streamlines_sparse.html"]).is_file()
    assert Path(streamed.artifacts["streamlines_sparse.html"]).is_relative_to(
        final.job_directory
    )
