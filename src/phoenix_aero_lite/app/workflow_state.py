"""Pure finite-state model for the Chinese desktop workflow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkflowTransitionError(ValueError):
    """Raised when a UI command violates workflow prerequisites."""


class WorkflowStage(str, Enum):
    EMPTY = "empty"
    MODEL_SELECTED = "model_selected"
    GEOMETRY_READY = "geometry_ready"
    MESHING = "meshing"
    MESH_READY = "mesh_ready"
    SOLVING = "solving"
    POSTPROCESSING = "postprocessing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowEvent(str, Enum):
    MODEL_SELECTED = "model_selected"
    INSPECTION_SUCCEEDED = "inspection_succeeded"
    INSPECTION_FAILED = "inspection_failed"
    MESH_STARTED = "mesh_started"
    MESH_SUCCEEDED = "mesh_succeeded"
    MESH_FAILED = "mesh_failed"
    SOLVE_STARTED = "solve_started"
    SOLVE_SUCCEEDED = "solve_succeeded"
    SOLVE_FAILED = "solve_failed"
    POSTPROCESS_SUCCEEDED = "postprocess_succeeded"
    POSTPROCESS_FAILED = "postprocess_failed"
    CANCEL = "cancel"
    RESET = "reset"


@dataclass(frozen=True, slots=True)
class WorkflowState:
    """Immutable UI state with derived command permissions."""

    stage: WorkflowStage
    failure_message: str | None = None
    recovery_stage: WorkflowStage = WorkflowStage.EMPTY

    @property
    def can_edit_parameters(self) -> bool:
        return self.stage in {
            WorkflowStage.EMPTY,
            WorkflowStage.MODEL_SELECTED,
            WorkflowStage.GEOMETRY_READY,
            WorkflowStage.MESH_READY,
            WorkflowStage.COMPLETED,
            WorkflowStage.FAILED,
            WorkflowStage.CANCELLED,
        }

    @property
    def can_mesh(self) -> bool:
        return self.stage is WorkflowStage.GEOMETRY_READY

    @property
    def can_solve(self) -> bool:
        return self.stage is WorkflowStage.MESH_READY

    @property
    def can_cancel(self) -> bool:
        return self.stage in {
            WorkflowStage.MESHING,
            WorkflowStage.SOLVING,
            WorkflowStage.POSTPROCESSING,
        }


def initial_workflow_state() -> WorkflowState:
    return WorkflowState(WorkflowStage.EMPTY)


def transition(
    state: WorkflowState,
    event: WorkflowEvent,
    failure_message: str | None = None,
) -> WorkflowState:
    """Apply one validated event and return a new immutable state."""

    if not isinstance(state, WorkflowState) or not isinstance(event, WorkflowEvent):
        raise WorkflowTransitionError("WORKFLOW_TRANSITION_INVALID")
    stage = state.stage
    if event is WorkflowEvent.MODEL_SELECTED and state.can_edit_parameters:
        return WorkflowState(WorkflowStage.MODEL_SELECTED)
    direct: dict[tuple[WorkflowStage, WorkflowEvent], WorkflowStage] = {
        (WorkflowStage.MODEL_SELECTED, WorkflowEvent.INSPECTION_SUCCEEDED): WorkflowStage.GEOMETRY_READY,
        (WorkflowStage.GEOMETRY_READY, WorkflowEvent.MESH_STARTED): WorkflowStage.MESHING,
        (WorkflowStage.MESHING, WorkflowEvent.MESH_SUCCEEDED): WorkflowStage.MESH_READY,
        (WorkflowStage.MESH_READY, WorkflowEvent.SOLVE_STARTED): WorkflowStage.SOLVING,
        (WorkflowStage.SOLVING, WorkflowEvent.SOLVE_SUCCEEDED): WorkflowStage.POSTPROCESSING,
        (WorkflowStage.POSTPROCESSING, WorkflowEvent.POSTPROCESS_SUCCEEDED): WorkflowStage.COMPLETED,
    }
    target = direct.get((stage, event))
    if target is not None:
        return WorkflowState(target)

    failure_events = {
        WorkflowEvent.INSPECTION_FAILED,
        WorkflowEvent.MESH_FAILED,
        WorkflowEvent.SOLVE_FAILED,
        WorkflowEvent.POSTPROCESS_FAILED,
    }
    if event in failure_events and stage in {
        WorkflowStage.MODEL_SELECTED,
        WorkflowStage.MESHING,
        WorkflowStage.SOLVING,
        WorkflowStage.POSTPROCESSING,
    }:
        recovery = {
            WorkflowStage.MODEL_SELECTED: WorkflowStage.MODEL_SELECTED,
            WorkflowStage.MESHING: WorkflowStage.GEOMETRY_READY,
            WorkflowStage.SOLVING: WorkflowStage.MESH_READY,
            WorkflowStage.POSTPROCESSING: WorkflowStage.MESH_READY,
        }[stage]
        return WorkflowState(
            WorkflowStage.FAILED,
            failure_message or "操作失败",
            recovery,
        )
    if event is WorkflowEvent.CANCEL and state.can_cancel:
        recovery = (
            WorkflowStage.GEOMETRY_READY
            if stage is WorkflowStage.MESHING
            else WorkflowStage.MESH_READY
        )
        return WorkflowState(WorkflowStage.CANCELLED, None, recovery)
    if event is WorkflowEvent.RESET and stage in {
        WorkflowStage.FAILED,
        WorkflowStage.CANCELLED,
    }:
        return WorkflowState(state.recovery_stage)
    raise WorkflowTransitionError("WORKFLOW_TRANSITION_NOT_ALLOWED")
