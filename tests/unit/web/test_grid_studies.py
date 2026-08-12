from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
import time
import json

import pytest

from phoenix_aero_lite.solver.convergence import ConvergenceStatus
from phoenix_aero_lite.web.grid_studies import GridStudyState, LocalGridStudyService
from phoenix_aero_lite.web.jobs import LocalJobService
from phoenix_aero_lite.web.models import JobRequest
from phoenix_aero_lite.models.parameters import MeshMode
from tests.unit.web.test_jobs import write_result_manifest


def _request() -> JobRequest:
    return JobRequest(
        velocity_m_s=20.0,
        angle_of_attack_deg=4.0,
        s_ref_m2=1.2,
        c_ref_m=0.3,
        mass_kg=2.5,
        density_kg_m3=1.225,
        dynamic_viscosity_pa_s=1.7894e-5,
        mesh_mode=MeshMode.STANDARD,
        target_cell_size_m=0.3,
        max_iterations=800,
    )


def _result(case_root: Path, target: float, *, stagnate_fine: bool = False):
    index = {0.45: 0, 0.3: 1, 0.2: 2}[round(target, 2)]
    counts = ((1000, 8000), (8000, 64000), (64000, 512000))[index]
    values = ((0.50, 0.050), (0.55, 0.045), (0.56, 0.043))[index]
    status = (
        ConvergenceStatus.STAGNATED
        if stagnate_fine and index == 2
        else ConvergenceStatus.CONVERGED
    )
    artifacts = []
    for name in ("history.csv", "flow.vtu", "surface_flow.vtu", "report.html"):
        path = case_root / name
        path.write_text("artifact", encoding="utf-8")
        artifacts.append(path)
    stdout = case_root / "stdout.txt"
    stderr = case_root / "stderr.txt"
    stdout.write_text("SU2", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    artifacts.extend((stdout, stderr))
    write_result_manifest(case_root, artifacts)
    convergence = SimpleNamespace(
        status=status,
        reason_code="TARGET_AND_FORCE_PLATEAU",
        final_cl=values[0],
        final_cd=values[1],
    )
    return SimpleNamespace(
        case_root=case_root,
        manifest_path=case_root / "case_manifest.json",
        fingerprint="a" * 64,
        reused_steps=(),
        executed_steps=("stage", "inspect", "mesh", "config", "solve", "parse", "visualize", "report"),
        stage_sources={},
        context={
            "convergence": convergence,
            "mesh_quality": {
                "node_count": counts[0],
                "cell_count": counts[1],
                "negative_quality_count": 0,
                "non_manifold_face_count": 0,
                "near_wall": {"required": False, "present": False},
            },
            "history_path": case_root / "history.csv",
            "flow_vtu": case_root / "flow.vtu",
            "surface_flow_vtu": case_root / "surface_flow.vtu",
            "report_path": case_root / "report.html",
            "process_result": SimpleNamespace(
                stdout_path=stdout, stderr_path=stderr
            ),
        }
    )


def _wait(service: LocalGridStudyService, study_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = service.get(study_id)
        if snapshot.state.is_terminal:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("grid study did not finish")


def test_grid_study_creates_three_independent_jobs_and_computes_gci(tmp_path):
    observed: list[float] = []

    def runner(_source, parameters, case_root, _cancellation):
        target = parameters.mesh.target_cell_size_m
        observed.append(target)
        return _result(case_root, target)

    jobs = LocalJobService(tmp_path / "jobs", runner=runner)
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)

    submitted = studies.submit("wing.step", b"STEP", _request())
    final = _wait(studies, submitted.study_id)

    assert final.state is GridStudyState.COMPLETED
    assert observed == pytest.approx([0.45, 0.3, 0.2])
    assert tuple(final.levels) == ("coarse", "medium", "fine")
    assert len({item.job_id for item in final.levels.values()}) == 3
    assert all(item.parent_job_id == final.study_id for item in final.levels.values())
    assert [item.cell_count for item in final.levels.values()] == [8000, 64000, 512000]
    assert all(item.elapsed_seconds is not None for item in final.levels.values())
    assert final.analysis_status == "computed"
    assert all(item["gci_computable"] for item in final.quantities.values())
    assert (final.study_directory / "grid_study.json").is_file()

    restored = LocalGridStudyService(tmp_path / "studies", job_service=jobs).get(
        final.study_id
    )
    assert restored.to_dict() == final.to_dict()


def test_grid_study_blocks_gci_when_any_child_is_not_converged(tmp_path):
    def runner(_source, parameters, case_root, _cancellation):
        return _result(
            case_root,
            parameters.mesh.target_cell_size_m,
            stagnate_fine=True,
        )

    jobs = LocalJobService(tmp_path / "jobs", runner=runner)
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    final = _wait(
        studies,
        studies.submit("wing.step", b"STEP", _request()).study_id,
    )

    assert final.state is GridStudyState.BLOCKED
    assert final.analysis_status == "blocked"
    assert "GRID_LEVEL_NOT_CONVERGED" in final.blocking_reasons
    assert final.quantities == {}


def test_grid_study_cancel_requests_cancellation_for_every_child(tmp_path):
    entered = threading.Event()

    def runner(_source, _parameters, _case_root, cancellation):
        entered.set()
        deadline = time.monotonic() + 3
        while not cancellation.is_cancelled and time.monotonic() < deadline:
            time.sleep(0.005)
        if cancellation.is_cancelled:
            raise RuntimeError("cancelled")
        raise RuntimeError("test runner timeout")

    jobs = LocalJobService(tmp_path / "jobs", runner=runner)
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    submitted = studies.submit("wing.step", b"STEP", _request())
    assert entered.wait(1)

    assert studies.cancel(submitted.study_id) is True
    final = _wait(studies, submitted.study_id)

    assert final.state is GridStudyState.CANCELLED
    assert all(item.state == "cancelled" for item in final.levels.values())
    assert final.blocking_reasons == ("GRID_STUDY_CANCELLED",)


def test_partial_completion_followed_by_cancel_remains_user_cancelled(tmp_path):
    calls = 0
    second_entered = threading.Event()

    def runner(_source, parameters, case_root, cancellation):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _result(case_root, parameters.mesh.target_cell_size_m)
        second_entered.set()
        while not cancellation.is_cancelled:
            time.sleep(0.005)
        raise RuntimeError("cancelled")

    jobs = LocalJobService(tmp_path / "jobs", runner=runner)
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    submitted = studies.submit("wing.step", b"STEP", _request())
    assert second_entered.wait(2)

    assert studies.cancel(submitted.study_id) is True
    final = _wait(studies, submitted.study_id)

    assert final.state is GridStudyState.CANCELLED
    assert final.cancellation_requested is True
    assert any(item.state == "completed" for item in final.levels.values())
    assert any(item.state == "cancelled" for item in final.levels.values())


def test_non_refining_actual_mesh_counts_persist_a_block_instead_of_raising(tmp_path):
    def runner(_source, parameters, case_root, _cancellation):
        result = _result(case_root, parameters.mesh.target_cell_size_m)
        result.context["mesh_quality"].update(node_count=1000, cell_count=8000)
        return result

    jobs = LocalJobService(tmp_path / "jobs", runner=runner)
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    final = _wait(
        studies,
        studies.submit("wing.step", b"STEP", _request()).study_id,
    )

    assert final.state is GridStudyState.BLOCKED
    assert final.analysis_status == "blocked"
    assert "GRID_CELL_COUNTS_NOT_REFINED" in final.blocking_reasons
    assert final.quantities == {}
    assert LocalGridStudyService(tmp_path / "studies", job_service=jobs).get(
        final.study_id
    ).state is GridStudyState.BLOCKED


def test_failed_partial_creation_is_persisted_with_submitted_child(tmp_path):
    jobs = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, parameters, case_root, _token: _result(
            case_root, parameters.mesh.target_cell_size_m
        ),
    )
    original_submit = jobs.submit
    attempts = 0

    def fail_second_submit(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("simulated creation interruption")
        return original_submit(*args, **kwargs)

    jobs.submit = fail_second_submit  # type: ignore[method-assign]
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)

    with pytest.raises(RuntimeError, match="creation interruption"):
        studies.submit("wing.step", b"STEP", _request())

    persisted = studies.list()
    assert len(persisted) == 1
    assert persisted[0].state is GridStudyState.FAILED
    assert len(persisted[0].levels) == 1
    assert persisted[0].blocking_reasons == ("GRID_STUDY_CREATION_FAILED",)


def test_restart_recovers_unrecorded_child_from_parent_id(tmp_path):
    jobs = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, parameters, case_root, _token: _result(
            case_root, parameters.mesh.target_cell_size_m
        ),
    )
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    original = studies.submit("wing.step", b"STEP", _request())
    path = original.study_directory / "grid_study.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = "queued"
    payload["analysis_status"] = "creating"
    payload["levels"] = {}
    path.write_text(json.dumps(payload), encoding="utf-8")

    restored = LocalGridStudyService(tmp_path / "studies", job_service=jobs).get(
        original.study_id
    )

    assert restored.state is GridStudyState.BLOCKED
    assert set(restored.levels) == {"coarse", "medium", "fine"}
    assert restored.blocking_reasons == ("GRID_STUDY_INTERRUPTED_ON_RESTART",)


def test_common_setup_fingerprint_includes_actual_model_content(tmp_path):
    jobs = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, parameters, case_root, _token: _result(
            case_root, parameters.mesh.target_cell_size_m
        ),
    )
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)

    first = studies.submit("wing.step", b"STEP-A", _request())
    second = studies.submit("wing.step", b"STEP-B", _request())

    assert first.common_setup_fingerprint != second.common_setup_fingerprint


def test_concurrent_polling_cannot_regress_terminal_study_state(tmp_path):
    jobs = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, parameters, case_root, _token: _result(
            case_root, parameters.mesh.target_cell_size_m
        ),
    )
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    study_id = studies.submit("wing.step", b"STEP", _request()).study_id
    observed: list[GridStudyState] = []

    def poll():
        for _ in range(30):
            observed.append(studies.get(study_id).state)

    workers = [threading.Thread(target=poll) for _ in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    final = _wait(studies, study_id)

    assert final.state is GridStudyState.COMPLETED
    assert observed
    assert all(studies.get(study_id).state is GridStudyState.COMPLETED for _ in range(20))
