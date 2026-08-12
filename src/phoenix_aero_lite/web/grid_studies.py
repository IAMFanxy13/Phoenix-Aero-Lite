"""Persistent three-job grid studies built on the existing local job queue."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
from threading import RLock
from typing import Mapping, cast
from uuid import uuid4

from phoenix_aero_lite.models.parameters import MeshMode
from phoenix_aero_lite.solver.grid_study import (
    AerodynamicGridLevel,
    analyze_aerodynamic_grid_study,
)
from phoenix_aero_lite.web.jobs import JobSnapshot, JobState, LocalJobService
from phoenix_aero_lite.web.models import JobRequest, MAX_STEP_BYTES


class GridStudyState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.BLOCKED,
            self.FAILED,
            self.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class GridStudyLevel:
    level: str
    job_id: str
    parent_job_id: str
    target_cell_size_m: float
    state: str
    convergence_status: str | None = None
    node_count: int | None = None
    cell_count: int | None = None
    cl: float | None = None
    cd: float | None = None
    elapsed_seconds: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "job_id": self.job_id,
            "parent_job_id": self.parent_job_id,
            "target_cell_size_m": self.target_cell_size_m,
            "state": self.state,
            "convergence_status": self.convergence_status,
            "node_count": self.node_count,
            "cell_count": self.cell_count,
            "cl": self.cl,
            "cd": self.cd,
            "elapsed_seconds": self.elapsed_seconds,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GridStudyLevel":
        target_cell_size = _optional_float(payload.get("target_cell_size_m"))
        if target_cell_size is None or target_cell_size <= 0.0:
            raise ValueError("GRID_STUDY_LEVEL_TARGET_INVALID")
        return cls(
            level=str(payload["level"]),
            job_id=str(payload["job_id"]),
            parent_job_id=str(payload["parent_job_id"]),
            target_cell_size_m=target_cell_size,
            state=str(payload["state"]),
            convergence_status=_optional_text(payload.get("convergence_status")),
            node_count=_optional_int(payload.get("node_count")),
            cell_count=_optional_int(payload.get("cell_count")),
            cl=_optional_float(payload.get("cl")),
            cd=_optional_float(payload.get("cd")),
            elapsed_seconds=_optional_float(payload.get("elapsed_seconds")),
        )


@dataclass(frozen=True, slots=True)
class GridStudySnapshot:
    study_id: str
    state: GridStudyState
    analysis_status: str
    created_at: str
    updated_at: str
    study_directory: Path
    original_filename: str
    request: Mapping[str, object]
    common_setup_fingerprint: str
    model_sha256: str
    levels: Mapping[str, GridStudyLevel]
    quantities: Mapping[str, Mapping[str, object]]
    blocking_reasons: tuple[str, ...] = ()
    cancellation_requested: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "study_id": self.study_id,
            "state": self.state.value,
            "analysis_status": self.analysis_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "study_directory": str(self.study_directory),
            "original_filename": self.original_filename,
            "request": dict(self.request),
            "common_setup_fingerprint": self.common_setup_fingerprint,
            "model_sha256": self.model_sha256,
            "levels": {
                name: level.to_dict() for name, level in self.levels.items()
            },
            "quantities": {
                name: dict(quantity) for name, quantity in self.quantities.items()
            },
            "blocking_reasons": list(self.blocking_reasons),
            "cancellation_requested": self.cancellation_requested,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GridStudySnapshot":
        if _optional_int(payload.get("schema_version")) != 1:
            raise ValueError("GRID_STUDY_SCHEMA_UNSUPPORTED")
        raw_levels = payload.get("levels")
        raw_quantities = payload.get("quantities")
        raw_request = payload.get("request")
        raw_reasons = payload.get("blocking_reasons", ())
        if not isinstance(raw_levels, Mapping) or not isinstance(
            raw_quantities, Mapping
        ) or not isinstance(raw_request, Mapping) or not isinstance(
            raw_reasons, (list, tuple)
        ):
            raise ValueError("GRID_STUDY_SCHEMA_INVALID")
        return cls(
            study_id=str(payload["study_id"]),
            state=GridStudyState(str(payload["state"])),
            analysis_status=str(payload["analysis_status"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            study_directory=Path(str(payload["study_directory"])),
            original_filename=str(payload["original_filename"]),
            request=dict(raw_request),
            common_setup_fingerprint=str(payload["common_setup_fingerprint"]),
            model_sha256=str(payload.get("model_sha256", "")),
            levels={
                str(name): GridStudyLevel.from_dict(value)
                for name, value in raw_levels.items()
                if isinstance(value, Mapping)
            },
            quantities={
                str(name): dict(value)
                for name, value in raw_quantities.items()
                if isinstance(value, Mapping)
            },
            blocking_reasons=tuple(str(value) for value in raw_reasons),
            cancellation_requested=bool(payload.get("cancellation_requested", False)),
        )


_LEVEL_FACTORS = {"coarse": 1.5, "medium": 1.0, "fine": 2.0 / 3.0}


class LocalGridStudyService:
    """Create and aggregate three independent jobs without bypassing gates."""

    def __init__(self, root: Path, *, job_service: LocalJobService) -> None:
        self._root = Path(root).resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)
        self._jobs = job_service
        self._lock = RLock()
        self._snapshots: dict[str, GridStudySnapshot] = {}
        self._restore()

    @property
    def root(self) -> Path:
        return self._root

    def submit(
        self,
        filename: str,
        content: bytes,
        request: JobRequest,
    ) -> GridStudySnapshot:
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".step", ".stp"}:
            raise ValueError("MODEL_MUST_BE_STEP")
        if not content:
            raise ValueError("MODEL_EMPTY")
        if len(content) > MAX_STEP_BYTES:
            raise ValueError("MODEL_TOO_LARGE")
        request.to_case_parameters(self._root / "validation")
        if request.mesh_mode is MeshMode.PREVIEW:
            raise ValueError("GRID_STUDY_REQUIRES_STANDARD_MESH")
        study_id = uuid4().hex
        study_directory = (self._root / study_id).resolve(strict=False)
        if not study_directory.is_relative_to(self._root):
            raise RuntimeError("GRID_STUDY_DIRECTORY_INVALID")
        study_directory.mkdir(parents=True)
        model_sha256 = hashlib.sha256(content).hexdigest()
        fingerprint = _common_setup_fingerprint(request, model_sha256)
        children: dict[str, GridStudyLevel] = {}
        now = _now()
        snapshot = GridStudySnapshot(
            study_id=study_id,
            state=GridStudyState.QUEUED,
            analysis_status="creating",
            created_at=now,
            updated_at=now,
            study_directory=study_directory,
            original_filename=Path(filename).name,
            request=request.to_dict(),
            common_setup_fingerprint=fingerprint,
            model_sha256=model_sha256,
            levels={},
            quantities={},
        )
        self._publish(snapshot)
        try:
            for level, factor in _LEVEL_FACTORS.items():
                level_request = replace(
                    request,
                    mesh_mode=MeshMode.STANDARD,
                    target_cell_size_m=request.target_cell_size_m * factor,
                )
                child = self._jobs.submit(
                    filename,
                    content,
                    level_request,
                    parent_job_id=study_id,
                )
                children[level] = _level_from_job(
                    level,
                    child,
                    target_cell_size_m=level_request.target_cell_size_m,
                )
                snapshot = replace(
                    snapshot,
                    updated_at=_now(),
                    levels=dict(children),
                )
                self._publish(snapshot)
        except Exception:
            for submitted_child in children.values():
                self._jobs.cancel(submitted_child.job_id)
            self._publish(
                replace(
                    snapshot,
                    state=GridStudyState.FAILED,
                    analysis_status="blocked",
                    updated_at=_now(),
                    levels=dict(children),
                    blocking_reasons=("GRID_STUDY_CREATION_FAILED",),
                )
            )
            raise
        snapshot = replace(
            snapshot,
            analysis_status="pending",
            updated_at=_now(),
            levels=dict(children),
        )
        self._publish(snapshot)
        return snapshot

    def get(self, study_id: str) -> GridStudySnapshot:
        with self._lock:
            snapshot = self._snapshots.get(study_id)
            if snapshot is None:
                raise KeyError(study_id)
            if snapshot.state.is_terminal:
                return snapshot
            return self._refresh(snapshot)

    def list(self) -> tuple[GridStudySnapshot, ...]:
        with self._lock:
            identifiers = tuple(self._snapshots)
        values = [self.get(identifier) for identifier in identifiers]
        return tuple(sorted(values, key=lambda item: item.created_at, reverse=True))

    def cancel(self, study_id: str) -> bool:
        snapshot = self.get(study_id)
        if snapshot.state.is_terminal:
            return False
        snapshot = replace(
            snapshot,
            cancellation_requested=True,
            updated_at=_now(),
        )
        self._publish(snapshot)
        requested = False
        for child in snapshot.levels.values():
            requested = self._jobs.cancel(child.job_id) or requested
        return requested

    def _refresh(self, snapshot: GridStudySnapshot) -> GridStudySnapshot:
        levels: dict[str, GridStudyLevel] = {}
        jobs: list[JobSnapshot] = []
        for level in _LEVEL_FACTORS:
            current = snapshot.levels.get(level)
            if current is None:
                continue
            try:
                child = self._jobs.get(current.job_id)
            except KeyError:
                updated = replace(
                    snapshot,
                    state=GridStudyState.FAILED,
                    analysis_status="blocked",
                    updated_at=_now(),
                    blocking_reasons=("GRID_LEVEL_JOB_MISSING",),
                )
                self._publish(updated)
                return updated
            jobs.append(child)
            levels[level] = _level_from_job(
                level,
                child,
                target_cell_size_m=current.target_cell_size_m,
            )
        if len(levels) < 3 and snapshot.analysis_status == "creating":
            return snapshot
        if any(not child.state.is_terminal for child in jobs):
            state = (
                GridStudyState.RUNNING
                if any(child.state is JobState.RUNNING for child in jobs)
                else GridStudyState.QUEUED
            )
            updated = replace(
                snapshot,
                state=state,
                updated_at=_now(),
                levels=levels,
            )
            self._publish(updated)
            return updated
        if snapshot.cancellation_requested and all(
            child.state.is_terminal for child in jobs
        ):
            updated = replace(
                snapshot,
                state=GridStudyState.CANCELLED,
                analysis_status="blocked",
                updated_at=_now(),
                levels=levels,
                blocking_reasons=("GRID_STUDY_CANCELLED",),
            )
            self._publish(updated)
            return updated
        reasons = _blocking_reasons(
            jobs, expected_fingerprint=snapshot.common_setup_fingerprint
        )
        if reasons:
            state = (
                GridStudyState.FAILED
                if any(child.state is JobState.FAILED for child in jobs)
                else GridStudyState.BLOCKED
            )
            updated = replace(
                snapshot,
                state=state,
                analysis_status="blocked",
                updated_at=_now(),
                levels=levels,
                quantities={},
                blocking_reasons=reasons,
            )
            self._publish(updated)
            return updated
        study_levels: list[AerodynamicGridLevel] = []
        for level in _LEVEL_FACTORS:
            item = levels[level]
            study_levels.append(
                AerodynamicGridLevel(
                level=level,
                node_count=cast(int, item.node_count),
                cell_count=cast(int, item.cell_count),
                cl=cast(float, item.cl),
                cd=cast(float, item.cd),
                convergence_status=str(item.convergence_status),
                common_setup_fingerprint=snapshot.common_setup_fingerprint,
                elapsed_seconds=item.elapsed_seconds,
                spatial_dimension=3,
                )
            )
        try:
            results = analyze_aerodynamic_grid_study(
                coarse=study_levels[0], medium=study_levels[1], fine=study_levels[2]
            )
        except (ArithmeticError, ValueError) as error:
            reason = str(error).strip() or "GRID_STUDY_ANALYSIS_INVALID"
            updated = replace(
                snapshot,
                state=GridStudyState.BLOCKED,
                analysis_status="blocked",
                updated_at=_now(),
                levels=levels,
                quantities={},
                blocking_reasons=(reason,),
            )
            self._publish(updated)
            return updated
        quantities = {name: result.to_dict() for name, result in results.items()}
        computable = all(result.gci_computable for result in results.values())
        updated = replace(
            snapshot,
            state=(
                GridStudyState.COMPLETED if computable else GridStudyState.BLOCKED
            ),
            analysis_status="computed" if computable else "blocked",
            updated_at=_now(),
            levels=levels,
            quantities=quantities,
            blocking_reasons=(
                ()
                if computable
                else tuple(
                    sorted(
                        {
                            reason
                            for result in results.values()
                            for reason in result.blocking_reasons
                        }
                    )
                )
            ),
        )
        self._publish(updated)
        return updated

    def _publish(self, snapshot: GridStudySnapshot) -> None:
        with self._lock:
            current = self._snapshots.get(snapshot.study_id)
            if (
                current is not None
                and current.state.is_terminal
                and not snapshot.state.is_terminal
            ):
                return
            self._snapshots[snapshot.study_id] = snapshot
            path = snapshot.study_directory / "grid_study.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            encoded = json.dumps(
                snapshot.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
            with temporary.open("x", encoding="utf-8") as destination:
                destination.write(encoded + "\n")
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, path)

    def _restore(self) -> None:
        for path in self._root.glob("*/grid_study.json"):
            try:
                snapshot = GridStudySnapshot.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if not snapshot.state.is_terminal:
                recovered = dict(snapshot.levels)
                base_target = _optional_float(
                    snapshot.request.get("target_cell_size_m")
                )
                if base_target is not None:
                    for child in self._jobs.list():
                        if child.parent_job_id != snapshot.study_id:
                            continue
                        child_target = _optional_float(
                            child.request.get("target_cell_size_m")
                        )
                        level = _level_for_target(base_target, child_target)
                        if level is not None and child_target is not None:
                            recovered[level] = _level_from_job(
                                level,
                                child,
                                target_cell_size_m=child_target,
                            )
                snapshot = replace(
                    snapshot,
                    state=(
                        GridStudyState.CANCELLED
                        if snapshot.cancellation_requested
                        else GridStudyState.BLOCKED
                    ),
                    analysis_status="blocked",
                    updated_at=_now(),
                    levels=recovered,
                    blocking_reasons=(
                        "GRID_STUDY_CANCELLED"
                        if snapshot.cancellation_requested
                        else "GRID_STUDY_INTERRUPTED_ON_RESTART",
                    ),
                )
                self._publish(snapshot)
            else:
                self._snapshots[snapshot.study_id] = snapshot


def _level_from_job(
    level: str,
    job: JobSnapshot,
    *,
    target_cell_size_m: float,
) -> GridStudyLevel:
    return GridStudyLevel(
        level=level,
        job_id=job.job_id,
        parent_job_id=job.parent_job_id or "",
        target_cell_size_m=target_cell_size_m,
        state=job.state.value,
        convergence_status=job.convergence_status,
        node_count=job.mesh_node_count,
        cell_count=job.mesh_cell_count,
        cl=job.cl,
        cd=job.cd,
        elapsed_seconds=job.elapsed_seconds,
    )


def _blocking_reasons(
    jobs: list[JobSnapshot], *, expected_fingerprint: str
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if any(child.state is not JobState.COMPLETED for child in jobs):
        reasons.add("GRID_LEVEL_EXECUTION_NOT_COMPLETED")
    if any(child.convergence_status != "converged" for child in jobs):
        reasons.add("GRID_LEVEL_NOT_CONVERGED")
    if any(
        child.mesh_node_count is None
        or child.mesh_cell_count is None
        or child.cl is None
        or child.cd is None
        or child.elapsed_seconds is None
        for child in jobs
    ):
        reasons.add("GRID_LEVEL_RESULT_INCOMPLETE")
    if any(
        child.mesh_node_count is not None
        and child.mesh_node_count <= 0
        or child.mesh_cell_count is not None
        and child.mesh_cell_count <= 0
        or child.cl is not None
        and not math.isfinite(child.cl)
        or child.cd is not None
        and not math.isfinite(child.cd)
        for child in jobs
    ):
        reasons.add("GRID_LEVEL_RESULT_INVALID")
    if any(_job_setup_fingerprint(child) != expected_fingerprint for child in jobs):
        reasons.add("GRID_COMMON_SETUP_MISMATCH")
    return tuple(sorted(reasons))


def _common_setup_fingerprint(request: JobRequest, model_sha256: str) -> str:
    payload = request.to_dict()
    payload.pop("target_cell_size_m", None)
    payload["mesh_mode"] = MeshMode.STANDARD.value
    payload["spatial_dimension"] = 3
    payload["model_sha256"] = model_sha256
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _job_setup_fingerprint(job: JobSnapshot) -> str:
    payload = dict(job.request)
    payload.pop("target_cell_size_m", None)
    payload["mesh_mode"] = MeshMode.STANDARD.value
    payload["spatial_dimension"] = 3
    source = job.job_directory / "input" / "model.step"
    payload["model_sha256"] = _sha256(source) if source.is_file() else ""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _level_for_target(base: float, candidate: float | None) -> str | None:
    if candidate is None:
        return None
    for level, factor in _LEVEL_FACTORS.items():
        if math.isclose(candidate, base * factor, rel_tol=1e-9, abs_tol=1e-12):
            return level
    return None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    parsed = int(str(value))
    return parsed if parsed >= 0 else None


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    parsed = float(str(value))
    return parsed if math.isfinite(parsed) else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
