"""Generic resumable step orchestration for Phoenix Aero Lite cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, MutableMapping

from phoenix_aero_lite.models.case_manifest import (
    ArtifactRecord,
    CaseManifest,
    StepRecord,
)


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Files and JSON-safe metadata published by one completed step."""

    artifacts: tuple[Path, ...]
    metadata: Mapping[str, object]


StepExecute = Callable[[MutableMapping[str, object]], StepOutcome]
StepRestore = Callable[[MutableMapping[str, object], StepRecord], None]


@dataclass(frozen=True, slots=True)
class WorkflowStepDefinition:
    """One ordered step and its explicit dependencies."""

    name: str
    dependencies: tuple[str, ...]
    execute: StepExecute
    restore: StepRestore | None = None
    input_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    """Resume/execution evidence for one orchestration call."""

    case_root: Path
    fingerprint: str
    reused_steps: tuple[str, ...]
    executed_steps: tuple[str, ...]
    manifest_path: Path
    context: Mapping[str, object]
    stage_sources: Mapping[str, str | None]
    cache_lease: object | None = None


class ResumableWorkflow:
    """Execute an ordered DAG and reuse only hash-valid contiguous outputs."""

    def __init__(
        self,
        case_root: Path,
        steps: tuple[WorkflowStepDefinition, ...],
    ) -> None:
        if not isinstance(case_root, Path) or not steps:
            raise ValueError("WORKFLOW_DEFINITION_INVALID")
        names = tuple(step.name for step in steps)
        if (
            any(not name or not isinstance(name, str) for name in names)
            or len(set(names)) != len(names)
        ):
            raise ValueError("WORKFLOW_DEFINITION_INVALID")
        seen: set[str] = set()
        for step in steps:
            if any(dependency not in seen for dependency in step.dependencies):
                raise ValueError("WORKFLOW_DEPENDENCY_INVALID")
            seen.add(step.name)
            if step.input_fingerprint is not None and (
                len(step.input_fingerprint) != 64
                or any(
                    character not in "0123456789abcdefABCDEF"
                    for character in step.input_fingerprint
                )
            ):
                raise ValueError("WORKFLOW_STEP_FINGERPRINT_INVALID")
        self._case_root = case_root.resolve(strict=False)
        self._steps = steps
        self._manifest_path = self._case_root / "case_manifest.json"

    def run(
        self,
        fingerprint: str,
        *,
        on_step: Callable[[str, str], None] | None = None,
        provenance: Mapping[str, object] | None = None,
        producer_id: str | None = None,
    ) -> WorkflowRunResult:
        """Resume from the last hash-valid step and atomically checkpoint."""

        if producer_id is not None and (
            not isinstance(producer_id, str) or not producer_id.strip()
        ):
            raise ValueError("WORKFLOW_PRODUCER_ID_INVALID")
        self._case_root.mkdir(parents=True, exist_ok=True)
        manifest = CaseManifest.load_or_new(
            self._manifest_path, fingerprint, provenance
        )
        context: dict[str, object] = {}
        reused: list[str] = []
        executed: list[str] = []
        completed: set[str] = set()
        stage_sources: dict[str, str | None] = {}
        for step in self._steps:
            if any(dependency not in completed for dependency in step.dependencies):
                raise RuntimeError("WORKFLOW_DEPENDENCY_INCOMPLETE")
            record = manifest.steps.get(step.name)
            dependencies_changed = any(
                dependency in executed for dependency in step.dependencies
            )
            has_explicit_fingerprint = step.input_fingerprint is not None
            if (
                record is not None
                and record.is_reusable(step.input_fingerprint)
                and (has_explicit_fingerprint or not dependencies_changed)
            ):
                if on_step is not None:
                    on_step(step.name, "reused")
                if step.restore is not None:
                    step.restore(context, record)
                reused.append(step.name)
                completed.add(step.name)
                stage_sources[step.name] = record.producer_id
                continue
            if on_step is not None:
                on_step(step.name, "running")
            manifest.steps[step.name] = StepRecord(
                status="running",
                input_fingerprint=step.input_fingerprint,
            )
            manifest.save_atomic(self._manifest_path)
            outcome = step.execute(context)
            if (
                not isinstance(outcome, StepOutcome)
                or not outcome.artifacts
            ):
                raise RuntimeError("WORKFLOW_STEP_OUTCOME_INVALID")
            artifacts = tuple(
                ArtifactRecord.from_path(path) for path in outcome.artifacts
            )
            completed_record = StepRecord(
                status="complete",
                artifacts=artifacts,
                metadata=dict(outcome.metadata),
                input_fingerprint=step.input_fingerprint,
                producer_id=producer_id,
            )
            manifest.steps[step.name] = completed_record
            manifest.save_atomic(self._manifest_path)
            if on_step is not None:
                on_step(step.name, "complete")
            if step.restore is not None:
                step.restore(context, completed_record)
            executed.append(step.name)
            completed.add(step.name)
            stage_sources[step.name] = producer_id
        return WorkflowRunResult(
            case_root=self._case_root,
            fingerprint=fingerprint.lower(),
            reused_steps=tuple(reused),
            executed_steps=tuple(executed),
            manifest_path=self._manifest_path.resolve(strict=True),
            context=context,
            stage_sources=stage_sources,
        )
