"""Persistent single-worker job service around the existing CFD pipeline."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import json
import hashlib
import inspect
import math
import os
from pathlib import Path
import shutil
from threading import RLock
import time
from typing import Callable, Mapping
from uuid import uuid4

from phoenix_aero_lite import __version__
from phoenix_aero_lite.models.evidence import (
    ConvergenceStatus,
    EvidenceStatus,
    ExecutionStatus,
    ScientificEvidence,
)
from phoenix_aero_lite.models.parameters import MeshMode
from phoenix_aero_lite.solver.credibility import assess_credibility
from phoenix_aero_lite.utilities.process_runner import CancellationToken
from phoenix_aero_lite.utilities.source_guard import sha256_file
from phoenix_aero_lite.visualization.web_scene import (
    InteractiveScene,
    export_pressure_surface,
    export_streamline_scene,
    export_velocity_slice,
    export_y_plus_surface,
)
from phoenix_aero_lite.web.models import JobRequest, MAX_STEP_BYTES
from phoenix_aero_lite.web.diagnostics import diagnostics_for_codes


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    state: JobState
    stage: str
    progress: int
    created_at: str
    updated_at: str
    job_directory: Path
    original_filename: str
    request: Mapping[str, object]
    credibility: str | None = None
    credibility_reason_codes: tuple[str, ...] = ()
    coefficients_usable: bool = False
    convergence_status: str | None = None
    cl: float | None = None
    cd: float | None = None
    mesh_node_count: int | None = None
    mesh_cell_count: int | None = None
    elapsed_seconds: float | None = None
    artifacts: Mapping[str, str] = None
    error_code: str | None = None
    parent_job_id: str | None = None
    retry_attempt: int = 0
    automatic_changes: Mapping[str, object] | None = None
    cache: Mapping[str, object] | None = None
    scientific_evidence: ScientificEvidence = field(default_factory=ScientificEvidence)

    def __post_init__(self) -> None:
        """Keep execution state synchronized without inferring scientific quality."""

        execution_status = _execution_status(self.state)
        if (
            self.state is JobState.FAILED
            and self.scientific_evidence.execution_status
            is ExecutionStatus.INTERRUPTED
        ):
            execution_status = ExecutionStatus.INTERRUPTED
        if self.scientific_evidence.execution_status is not execution_status:
            object.__setattr__(
                self,
                "scientific_evidence",
                replace(
                    self.scientific_evidence,
                    execution_status=execution_status,
                ),
            )

    def to_dict(self) -> dict[str, object]:
        evidence = self.scientific_evidence
        return {
            "schema_version": 2,
            "job_id": self.job_id,
            "state": self.state.value,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "job_directory": str(self.job_directory),
            "original_filename": self.original_filename,
            "request": dict(self.request),
            "credibility": self.credibility,
            "credibility_reason_codes": list(self.credibility_reason_codes),
            "coefficients_usable": self.coefficients_usable,
            "convergence_status": self.convergence_status,
            "cl": self.cl,
            "cd": self.cd,
            "mesh_node_count": self.mesh_node_count,
            "mesh_cell_count": self.mesh_cell_count,
            "elapsed_seconds": self.elapsed_seconds,
            "artifacts": dict(self.artifacts or {}),
            "error_code": self.error_code,
            "parent_job_id": self.parent_job_id,
            "retry_attempt": self.retry_attempt,
            "automatic_changes": dict(self.automatic_changes or {}),
            "cache": dict(self.cache or {}),
            "execution_status": evidence.execution_status.value,
            "scientific_use_level": evidence.scientific_use_level.value,
            "validation_level": (
                evidence.validation_level.value if evidence.validation_level else None
            ),
            "quantity_evidence": {
                name: quantity.to_dict()
                for name, quantity in sorted(evidence.quantities.items())
            },
            "scientific_evidence": evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "JobSnapshot":
        try:
            schema_version = int(payload.get("schema_version", 1))
        except (TypeError, ValueError):
            raise ValueError("JOB_SCHEMA_VERSION_INVALID") from None
        if schema_version not in {1, 2}:
            raise ValueError("JOB_SCHEMA_VERSION_UNSUPPORTED")
        state = JobState(str(payload["state"]))
        raw_evidence = payload.get("scientific_evidence")
        if schema_version == 2 and isinstance(raw_evidence, Mapping):
            evidence = ScientificEvidence.from_dict(raw_evidence)
            coefficients_usable = bool(payload.get("coefficients_usable", False))
        else:
            # Schema-v1 values cannot establish provenance, validation or
            # per-quantity permissions.  Preserve the record, never promote it.
            evidence = ScientificEvidence(
                execution_status=_execution_status(state),
                blocking_reasons=("LEGACY_SCIENTIFIC_EVIDENCE_MISSING",),
            )
            coefficients_usable = False
        return cls(
            job_id=str(payload["job_id"]),
            state=state,
            stage=str(payload["stage"]),
            progress=int(payload["progress"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            job_directory=Path(str(payload["job_directory"])),
            original_filename=str(payload["original_filename"]),
            request=dict(payload.get("request", {})),
            credibility=payload.get("credibility"),
            credibility_reason_codes=tuple(payload.get("credibility_reason_codes", ())),
            coefficients_usable=coefficients_usable,
            convergence_status=payload.get("convergence_status"),
            cl=payload.get("cl"),
            cd=payload.get("cd"),
            mesh_node_count=_optional_nonnegative_int(payload.get("mesh_node_count")),
            mesh_cell_count=_optional_nonnegative_int(payload.get("mesh_cell_count")),
            elapsed_seconds=_optional_nonnegative_float(payload.get("elapsed_seconds")),
            artifacts=dict(payload.get("artifacts", {})),
            error_code=payload.get("error_code"),
            parent_job_id=payload.get("parent_job_id"),
            retry_attempt=int(payload.get("retry_attempt", 0)),
            automatic_changes=dict(payload.get("automatic_changes", {})),
            cache=dict(payload.get("cache", {})),
            scientific_evidence=evidence,
        )


def _execution_status(state: JobState) -> ExecutionStatus:
    return ExecutionStatus(state.value)


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _optional_nonnegative_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else None


def _mapping_nonnegative_int(
    value: object, key: str
) -> int | None:
    if not isinstance(value, Mapping):
        return None
    return _optional_nonnegative_int(value.get(key))


JobRunner = Callable[..., object]
CacheCleanup = Callable[[], Mapping[str, object]]
PressureSceneBuilder = Callable[[Path, Path, str], InteractiveScene]
YPlusSceneBuilder = Callable[..., InteractiveScene]
VelocitySceneBuilder = Callable[[Path, Path, str], InteractiveScene]
StreamlineSceneBuilder = Callable[..., InteractiveScene]


class LocalJobService:
    """Run at most one heavy CFD case while serving persistent snapshots."""

    def __init__(
        self,
        root: Path,
        *,
        runner: JobRunner,
        pressure_scene_builder: PressureSceneBuilder | None = None,
        y_plus_scene_builder: YPlusSceneBuilder | None = None,
        velocity_scene_builder: VelocitySceneBuilder | None = None,
        streamline_scene_builder: StreamlineSceneBuilder | None = None,
        cache_policy: Mapping[str, object] | None = None,
        cache_cleanup: CacheCleanup | None = None,
    ) -> None:
        self._root = Path(root).resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)
        self._runner = runner
        try:
            runner_parameters = inspect.signature(runner).parameters
            self._runner_accepts_progress = "progress_callback" in runner_parameters
            self._runner_accepts_producer_id = "producer_id" in runner_parameters
        except (TypeError, ValueError):
            self._runner_accepts_progress = False
            self._runner_accepts_producer_id = False
        self._pressure_scene_builder = (
            pressure_scene_builder or export_pressure_surface
        )
        self._y_plus_scene_builder = y_plus_scene_builder or export_y_plus_surface
        self._velocity_scene_builder = velocity_scene_builder or export_velocity_slice
        self._streamline_scene_builder = (
            streamline_scene_builder or export_streamline_scene
        )
        self._cache_policy = dict(cache_policy or {})
        self._cache_cleanup = cache_cleanup
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pal-cfd")
        self._lock = RLock()
        self._snapshots: dict[str, JobSnapshot] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._futures: dict[str, Future] = {}
        self._restore_history()

    @property
    def root(self) -> Path:
        return self._root

    def submit(
        self,
        filename: str,
        content: bytes,
        request: JobRequest,
        *,
        parent_job_id: str | None = None,
        retry_attempt: int = 0,
        automatic_changes: Mapping[str, object] | None = None,
    ) -> JobSnapshot:
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".step", ".stp"}:
            raise ValueError("MODEL_MUST_BE_STEP")
        if not content:
            raise ValueError("MODEL_EMPTY")
        if len(content) > MAX_STEP_BYTES:
            raise ValueError("MODEL_TOO_LARGE")
        job_id = uuid4().hex
        job_directory = (self._root / job_id).resolve(strict=False)
        if not job_directory.is_relative_to(self._root):
            raise RuntimeError("JOB_DIRECTORY_INVALID")
        input_path = job_directory / "input" / "model.step"
        input_path.parent.mkdir(parents=True)
        input_path.write_bytes(content)
        now = _now()
        snapshot = JobSnapshot(
            job_id=job_id,
            state=JobState.QUEUED,
            stage="queued",
            progress=0,
            created_at=now,
            updated_at=now,
            job_directory=job_directory,
            original_filename=Path(filename).name,
            request=request.to_dict(),
            artifacts={},
            parent_job_id=parent_job_id,
            retry_attempt=retry_attempt,
            automatic_changes=dict(automatic_changes or {}),
        )
        token = CancellationToken()
        with self._lock:
            self._snapshots[job_id] = snapshot
            self._tokens[job_id] = token
            self._persist(snapshot)
            self._futures[job_id] = self._executor.submit(
                self._execute, job_id, input_path, request, token
            )
        return snapshot

    def retry_conservative(self, job_id: str) -> JobSnapshot:
        original = self.get(job_id)
        if not original.state.is_terminal:
            raise ValueError("JOB_CONSERVATIVE_RETRY_NOT_TERMINAL")
        if original.retry_attempt >= 1 or any(
            item.parent_job_id == job_id for item in self.list()
        ):
            raise ValueError("JOB_CONSERVATIVE_RETRY_ALREADY_USED")
        codes = tuple(
            value
            for value in (original.error_code, *original.credibility_reason_codes)
            if value
        )
        diagnostics = diagnostics_for_codes(codes)
        if not any(item.conservative_retry_allowed for item in diagnostics):
            raise ValueError("JOB_CONSERVATIVE_RETRY_NOT_ALLOWED")
        payload = dict(original.request)
        old_iterations = int(payload["max_iterations"])
        new_iterations = min(max(old_iterations + 200, math.ceil(old_iterations * 1.5)), 2000)
        changes: dict[str, object] = {
            "max_iterations": {
                "old": old_iterations,
                "new": new_iterations,
                "rationale_zh": "增加迭代预算，给残差和升阻力系数更多稳定时间。",
            }
        }
        payload["max_iterations"] = new_iterations
        if (
            "NEAR_WALL_LAYER_NOT_VALIDATED" in codes
            and payload["mesh_mode"] == MeshMode.PREVIEW.value
        ):
            payload["mesh_mode"] = MeshMode.FINE.value
            changes["mesh_mode"] = {
                "old": MeshMode.PREVIEW.value,
                "new": MeshMode.FINE.value,
                "rationale_zh": "改用细致网格路径，以便生成并检查近壁层；是否可用仍由真实质量与收敛门槛决定。",
            }
        if original.error_code == "MESH_FAILED":
            old_size = float(payload["target_cell_size_m"])
            new_size = old_size * 1.25
            payload["target_cell_size_m"] = new_size
            changes["target_cell_size_m"] = {
                "old": old_size,
                "new": new_size,
                "rationale_zh": "暂时放宽全局目标尺寸，降低小特征导致网格失败的概率。",
            }
        request = _request_from_mapping(payload)
        input_path = original.job_directory / "input" / "model.step"
        content = input_path.read_bytes()
        return self.submit(
            original.original_filename,
            content,
            request,
            parent_job_id=job_id,
            retry_attempt=1,
            automatic_changes=changes,
        )

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            try:
                return self._snapshots[job_id]
            except KeyError:
                raise KeyError("JOB_NOT_FOUND") from None

    def list(self) -> tuple[JobSnapshot, ...]:
        with self._lock:
            return tuple(
                sorted(self._snapshots.values(), key=lambda item: item.created_at)
            )

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            snapshot = self.get(job_id)
            if snapshot.state.is_terminal:
                return False
            self._tokens[job_id].cancel()
            future = self._futures.get(job_id)
            if future is not None and future.cancel():
                self._publish(
                    replace(
                        snapshot,
                        state=JobState.CANCELLED,
                        stage="cancelled",
                        progress=100,
                        updated_at=_now(),
                        credibility="invalid",
                        error_code="JOB_CANCELLED",
                        scientific_evidence=_terminal_evidence(
                            JobState.CANCELLED, "JOB_CANCELLED"
                        ),
                    )
                )
            return True

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def build_pressure_scene(
        self,
        job_id: str,
        field: str,
        *,
        range_min: float | None = None,
        range_max: float | None = None,
    ) -> JobSnapshot:
        if field not in {"cp", "pressure"}:
            raise ValueError("PRESSURE_FIELD_INVALID")
        with self._lock:
            snapshot = self.get(job_id)
            selected = dict(snapshot.artifacts or {}).get("surface_flow.vtu")
        if selected is None:
            raise ValueError("SURFACE_FLOW_RESULT_MISSING")
        source = Path(selected).resolve(strict=True)
        if not source.is_relative_to(snapshot.job_directory):
            raise ValueError("SURFACE_FLOW_RESULT_INVALID")
        name = f"pressure_{field}.html"
        output = snapshot.job_directory / "results" / "web" / name
        scene = self._pressure_scene_builder(
            source, output, field, range_min=range_min, range_max=range_max
        )
        return self._register_scene(snapshot, name, scene)

    def build_velocity_scene(
        self,
        job_id: str,
        preset: str,
        *,
        position: float = 0.0,
        opacity: float = 1.0,
        visible: bool = True,
    ) -> JobSnapshot:
        if preset not in {"longitudinal", "wing", "wake"}:
            raise ValueError("VELOCITY_SLICE_PRESET_INVALID")
        snapshot = self.get(job_id)
        source = self._job_artifact(snapshot, "flow.vtu", "VOLUME_FLOW_RESULT")
        name = f"velocity_{preset}.html"
        scene = self._velocity_scene_builder(
            source,
            snapshot.job_directory / "results" / "web" / name,
            preset,
            position=position,
            opacity=opacity,
            visible=visible,
        )
        return self._register_scene(snapshot, name, scene)

    def build_y_plus_scene(
        self,
        job_id: str,
        *,
        range_min: float | None = None,
        range_max: float | None = None,
    ) -> JobSnapshot:
        snapshot = self.get(job_id)
        evidence = snapshot.scientific_evidence.quantities.get("y_plus")
        if (
            evidence is None
            or evidence.evidence_status
            not in {
                EvidenceStatus.COMPUTED,
                EvidenceStatus.MEASURED,
                EvidenceStatus.VERIFIED,
            }
            or not evidence.usable_for_diagnostic
        ):
            raise ValueError("Y_PLUS_EVIDENCE_UNAVAILABLE")
        source = self._job_artifact(
            snapshot, "surface_flow.vtu", "SURFACE_FLOW_RESULT"
        )
        name = "y_plus.html"
        scene = self._y_plus_scene_builder(
            source,
            snapshot.job_directory / "results" / "web" / name,
            range_min=range_min,
            range_max=range_max,
        )
        return self._register_scene(snapshot, name, scene)

    def build_streamline_scene(
        self,
        job_id: str,
        density: str,
        *,
        line_width: float = 3.0,
        opacity: float = 1.0,
        visible: bool = True,
    ) -> JobSnapshot:
        if density not in {"sparse", "standard", "dense"}:
            raise ValueError("STREAMLINE_DENSITY_INVALID")
        snapshot = self.get(job_id)
        volume = self._job_artifact(snapshot, "flow.vtu", "VOLUME_FLOW_RESULT")
        surface = self._job_artifact(
            snapshot, "surface_flow.vtu", "SURFACE_FLOW_RESULT"
        )
        angle = math.radians(float(snapshot.request["angle_of_attack_deg"]))
        flow_direction = (math.cos(angle), 0.0, math.sin(angle))
        name = f"streamlines_{density}.html"
        scene = self._streamline_scene_builder(
            volume,
            surface,
            snapshot.job_directory / "results" / "web" / name,
            flow_direction=flow_direction,
            density=density,
            line_width=line_width,
            opacity=opacity,
            visible=visible,
        )
        return self._register_scene(snapshot, name, scene)

    def _job_artifact(
        self, snapshot: JobSnapshot, name: str, error_prefix: str
    ) -> Path:
        selected = dict(snapshot.artifacts or {}).get(name)
        if selected is None:
            raise ValueError(f"{error_prefix}_MISSING")
        path = Path(selected).resolve(strict=True)
        if not path.is_relative_to(snapshot.job_directory):
            raise ValueError(f"{error_prefix}_INVALID")
        return path

    def _register_scene(
        self, snapshot: JobSnapshot, name: str, scene: InteractiveScene
    ) -> JobSnapshot:
        scene_path = scene.output_path.resolve(strict=True)
        if not scene_path.is_relative_to(snapshot.job_directory):
            raise ValueError("RESULT_SCENE_PATH_INVALID")
        current = self.get(snapshot.job_id)
        updated = replace(
            current,
            updated_at=_now(),
            artifacts={**dict(current.artifacts or {}), name: str(scene_path)},
        )
        self._publish(updated)
        return updated

    def _execute(
        self,
        job_id: str,
        input_path: Path,
        request: JobRequest,
        token: CancellationToken,
    ) -> None:
        started = time.perf_counter()
        snapshot = self.get(job_id)
        if token.is_cancelled:
            self._publish(
                replace(
                    snapshot,
                    state=JobState.CANCELLED,
                    stage="cancelled",
                    progress=100,
                    updated_at=_now(),
                    credibility="invalid",
                    error_code="JOB_CANCELLED",
                    scientific_evidence=_terminal_evidence(
                        JobState.CANCELLED, "JOB_CANCELLED"
                    ),
                )
            )
            return
        self._publish(
            replace(
                snapshot,
                state=JobState.RUNNING,
                stage="pipeline",
                progress=10,
                updated_at=_now(),
            )
        )
        try:
            case_root = snapshot.job_directory / "case"
            case_root.mkdir(parents=True, exist_ok=True)
            parameters = request.to_case_parameters(case_root)
            def report_progress(stage: str, progress: int) -> None:
                normalized = max(10, min(99, int(progress)))
                with self._lock:
                    current = self.get(job_id)
                    if current.state.is_terminal or token.is_cancelled:
                        return
                    self._publish(
                        replace(
                            current,
                            stage=str(stage),
                            progress=max(current.progress, normalized),
                            updated_at=_now(),
                        )
                    )

            runner_keywords = {}
            if self._runner_accepts_progress:
                runner_keywords["progress_callback"] = report_progress
            if self._runner_accepts_producer_id:
                runner_keywords["producer_id"] = job_id
            result = self._runner(
                input_path,
                parameters,
                case_root,
                token,
                **runner_keywords,
            )
            convergence = result.context["convergence"]
            mesh_quality = result.context.get("mesh_quality")
            credibility = result.context.get("credibility") or assess_credibility(
                convergence, mesh_quality
            )
            cache_lease = getattr(result, "cache_lease", None)
            try:
                artifacts, artifact_validation = self._materialize_result_artifacts(
                    snapshot, result
                )
            finally:
                if cache_lease is not None:
                    release = getattr(cache_lease, "release", None)
                    if not callable(release):
                        raise RuntimeError("CACHE_LEASE_INVALID")
                    release()
            reused_steps = tuple(getattr(result, "reused_steps", ()))
            executed_steps = tuple(getattr(result, "executed_steps", ()))
            stage_sources = dict(getattr(result, "stage_sources", {}))
            reused_sources = {
                step: stage_sources.get(step)
                for step in reused_steps
            }
            if any(
                not isinstance(source_id, str) or not source_id.strip()
                for source_id in reused_sources.values()
            ):
                raise RuntimeError("CACHE_SOURCE_PROVENANCE_MISSING")
            unique_sources = set(reused_sources.values())
            source_job_id = next(iter(unique_sources)) if len(unique_sources) == 1 else None
            cleanup_report: dict[str, object] = {}
            if self._cache_cleanup is not None:
                cleaned = self._cache_cleanup()
                if not isinstance(cleaned, Mapping):
                    raise RuntimeError("CACHE_CLEANUP_INVALID")
                cleanup_report = dict(cleaned)
                if cleanup_report.get("limit_satisfied") is False:
                    raise RuntimeError("CACHE_LIMIT_NOT_ENFORCED")
            cache = {
                "fingerprint": getattr(result, "fingerprint", None),
                "source_job_id": source_job_id,
                "source_job_ids": reused_sources,
                "created_version": __version__,
                "dependencies": "case_manifest.json",
                "manifest_sha256": artifact_validation["manifest_sha256"],
                "hash_validation": True,
                "valid": True,
                "reused_steps": list(reused_steps),
                "executed_steps": list(executed_steps),
                "post_materialization_cleanup": cleanup_report,
                "cache_entry_retained": Path(result.case_root).is_dir(),
                **self._cache_policy,
            }
            self._publish(
                replace(
                    self.get(job_id),
                    state=JobState.COMPLETED,
                    stage="completed",
                    progress=100,
                    updated_at=_now(),
                    credibility=credibility.level.value,
                    credibility_reason_codes=credibility.reason_codes,
                    coefficients_usable=credibility.coefficients_usable,
                    convergence_status=convergence.status.value,
                    cl=convergence.final_cl,
                    cd=convergence.final_cd,
                    mesh_node_count=_mapping_nonnegative_int(
                        mesh_quality, "node_count"
                    ),
                    mesh_cell_count=_mapping_nonnegative_int(
                        mesh_quality, "cell_count"
                    ),
                    elapsed_seconds=time.perf_counter() - started,
                    artifacts=artifacts,
                    cache=cache,
                    scientific_evidence=credibility.scientific_evidence,
                )
            )

        except Exception as error:
            cancelled = token.is_cancelled
            terminal_state = JobState.CANCELLED if cancelled else JobState.FAILED
            error_code = (
                "JOB_CANCELLED"
                if cancelled
                else (str(error).strip() or type(error).__name__)
            )
            self._publish(
                replace(
                    self.get(job_id),
                    state=terminal_state,
                    stage="cancelled" if cancelled else "failed",
                    progress=100,
                    updated_at=_now(),
                    credibility="invalid",
                    coefficients_usable=False,
                    error_code=error_code,
                    scientific_evidence=_terminal_evidence(
                        terminal_state, error_code
                    ),
                )
            )

    def _materialize_result_artifacts(
        self, snapshot, result
    ) -> tuple[dict[str, str], dict[str, object]]:
        case_root = Path(result.case_root).resolve(strict=True)
        manifest_candidate = Path(result.manifest_path)
        if manifest_candidate.is_symlink() or not manifest_candidate.is_file():
            raise RuntimeError("CACHE_MANIFEST_INVALID")
        manifest_path = manifest_candidate.resolve(strict=True)
        manifest_sha256 = sha256_file(manifest_path)
        manifest_size = manifest_path.stat().st_size
        sources: list[tuple[str, Path]] = []
        for name, key in (
            ("history.csv", "history_path"),
            ("flow.vtu", "flow_vtu"),
            ("surface_flow.vtu", "surface_flow_vtu"),
            ("report.html", "report_path"),
        ):
            selected = result.context.get(key)
            if selected is None or not Path(selected).is_file():
                raise RuntimeError("CACHE_ARTIFACT_SET_INCOMPLETE")
            sources.append((name, Path(selected)))
        process = result.context.get("process_result")
        for name, attribute in (
            ("solver_stdout.txt", "stdout_path"),
            ("solver_stderr.txt", "stderr_path"),
        ):
            selected = getattr(process, attribute, None)
            if selected is not None:
                if not Path(selected).is_file():
                    raise RuntimeError("CACHE_ARTIFACT_SET_INCOMPLETE")
                sources.append((name, Path(selected)))

        expected = _manifest_artifact_index(manifest_path, case_root)

        results_directory = snapshot.job_directory / "results"
        if results_directory.exists():
            raise RuntimeError("CACHE_ARTIFACT_DESTINATION_EXISTS")
        staging = snapshot.job_directory / f".results.{uuid4().hex}.tmp"
        staging.mkdir()
        try:
            for name, source in sources:
                resolved = source.resolve(strict=True)
                record = expected.get(resolved)
                if record is None:
                    raise RuntimeError("CACHE_ARTIFACT_NOT_IN_MANIFEST")
                _copy_verified(
                    resolved,
                    staging / name,
                    expected_sha256=record["sha256"],
                    expected_size=record["size"],
                )
            _copy_verified(
                manifest_path,
                staging / "case_manifest.json",
                expected_sha256=manifest_sha256,
                expected_size=manifest_size,
            )
            os.replace(staging, results_directory)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        artifacts = {
            name: str((results_directory / name).resolve(strict=True))
            for name, _source in sources
        }
        artifacts["case_manifest.json"] = str(
            (results_directory / "case_manifest.json").resolve(strict=True)
        )
        return artifacts, {"manifest_sha256": manifest_sha256}

    def _publish(self, snapshot: JobSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.job_id] = snapshot
            self._persist(snapshot)

    def _persist(self, snapshot: JobSnapshot) -> None:
        path = snapshot.job_directory / "job.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        encoded = json.dumps(
            snapshot.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True
        )
        with temporary.open("x", encoding="utf-8") as destination:
            destination.write(encoded + "\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)

    def _restore_history(self) -> None:
        for path in self._root.glob("*/job.json"):
            try:
                snapshot = JobSnapshot.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if not snapshot.state.is_terminal:
                snapshot = replace(
                    snapshot,
                    state=JobState.FAILED,
                    stage="failed",
                    progress=100,
                    updated_at=_now(),
                    credibility="invalid",
                    error_code="JOB_INTERRUPTED_BY_RESTART",
                    scientific_evidence=replace(
                        snapshot.scientific_evidence,
                        execution_status=ExecutionStatus.INTERRUPTED,
                        convergence_status=ConvergenceStatus.INCOMPLETE,
                        blocking_reasons=("JOB_INTERRUPTED_BY_RESTART",),
                    ),
                )
                self._persist(snapshot)
            elif "surface_flow.vtu" not in (snapshot.artifacts or {}):
                flow = dict(snapshot.artifacts or {}).get("flow.vtu")
                candidate = Path(flow).with_name("surface_flow.vtu") if flow else None
                if (
                    candidate is not None
                    and candidate.is_file()
                    and candidate.resolve(strict=True).is_relative_to(
                        snapshot.job_directory.resolve(strict=False)
                    )
                ):
                    snapshot = replace(
                        snapshot,
                        artifacts={
                            **dict(snapshot.artifacts or {}),
                            "surface_flow.vtu": str(candidate.resolve(strict=True)),
                        },
                    )
                    self._persist(snapshot)
            self._snapshots[snapshot.job_id] = snapshot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_artifact_index(
    manifest_path: Path,
    case_root: Path,
) -> dict[Path, dict[str, object]]:
    manifest = Path(manifest_path)
    root = Path(case_root).resolve(strict=True)
    if (
        manifest.is_symlink()
        or not manifest.is_file()
        or not manifest.resolve(strict=True).is_relative_to(root)
    ):
        raise RuntimeError("CACHE_MANIFEST_INVALID")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        steps = payload["steps"]
        if not isinstance(steps, Mapping):
            raise TypeError
        index: dict[Path, dict[str, object]] = {}
        for step in steps.values():
            if not isinstance(step, Mapping) or step.get("status") != "complete":
                continue
            records = step.get("artifacts", ())
            if not isinstance(records, list):
                raise TypeError
            for record in records:
                if not isinstance(record, Mapping):
                    raise TypeError
                raw_path = Path(str(record["path"]))
                if raw_path.is_symlink():
                    raise TypeError
                path = raw_path.resolve(strict=True)
                digest = str(record["sha256"]).upper()
                size = record["size"]
                if (
                    not path.is_relative_to(root)
                    or len(digest) != 64
                    or any(character not in "0123456789ABCDEF" for character in digest)
                    or isinstance(size, bool)
                    or not isinstance(size, int)
                    or size < 0
                    or path in index
                ):
                    raise TypeError
                index[path] = {"sha256": digest, "size": size}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("CACHE_MANIFEST_INVALID") from None
    if not index:
        raise RuntimeError("CACHE_MANIFEST_INVALID")
    return index


def _copy_verified(
    source: Path,
    destination: Path,
    *,
    expected_sha256: object,
    expected_size: object,
) -> Path:
    resolved_source = Path(source)
    if resolved_source.is_symlink():
        raise RuntimeError("CACHE_ARTIFACT_HASH_MISMATCH")
    resolved_source = resolved_source.resolve(strict=True)
    target = Path(destination).resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    digest = hashlib.sha256()
    size = 0
    try:
        with resolved_source.open("rb") as source_stream, temporary.open("xb") as output:
            for block in iter(lambda: source_stream.read(1024 * 1024), b""):
                output.write(block)
                digest.update(block)
                size += len(block)
            output.flush()
            os.fsync(output.fileno())
        if (
            digest.hexdigest().upper() != str(expected_sha256).upper()
            or size != expected_size
        ):
            raise RuntimeError("CACHE_ARTIFACT_HASH_MISMATCH")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.resolve(strict=True)


def _terminal_evidence(state: JobState, error_code: str) -> ScientificEvidence:
    if state is JobState.CANCELLED:
        execution = ExecutionStatus.CANCELLED
    else:
        execution = ExecutionStatus.FAILED
    incomplete_codes = {
        "JOB_CANCELLED",
        "PIPELINE_SOLVE_CANCELLED",
        "PIPELINE_SOLVE_TIMED_OUT",
        "PIPELINE_SOLVE_START_FAILED",
        "PIPELINE_SOLVE_NONZERO_EXIT",
        "JOB_INTERRUPTED_BY_RESTART",
    }
    convergence = (
        ConvergenceStatus.INCOMPLETE
        if error_code in incomplete_codes
        else (
            ConvergenceStatus.DIVERGED
            if error_code == "HISTORY_NONFINITE"
            else (
                ConvergenceStatus.INVALID
                if error_code.startswith("HISTORY_")
                else ConvergenceStatus.NOT_EVALUATED
            )
        )
    )
    return ScientificEvidence(
        execution_status=execution,
        convergence_status=convergence,
        blocking_reasons=(error_code,),
    )


def _request_from_mapping(payload: Mapping[str, object]) -> JobRequest:
    return JobRequest(
        velocity_m_s=float(payload["velocity_m_s"]),
        angle_of_attack_deg=float(payload["angle_of_attack_deg"]),
        s_ref_m2=float(payload["s_ref_m2"]),
        c_ref_m=float(payload["c_ref_m"]),
        mass_kg=float(payload["mass_kg"]),
        density_kg_m3=float(payload["density_kg_m3"]),
        dynamic_viscosity_pa_s=float(payload["dynamic_viscosity_pa_s"]),
        mesh_mode=MeshMode(str(payload["mesh_mode"])),
        target_cell_size_m=float(payload["target_cell_size_m"]),
        max_iterations=int(payload["max_iterations"]),
    )
