from __future__ import annotations

import pytest

from phoenix_aero_lite.app.workflow_state import (
    WorkflowEvent,
    WorkflowStage,
    WorkflowTransitionError,
    initial_workflow_state,
    transition,
)


def test_guards_mesh_solve_and_parameter_editing():
    state = initial_workflow_state()
    assert not state.can_mesh and not state.can_solve
    state = transition(state, WorkflowEvent.MODEL_SELECTED)
    assert not state.can_mesh
    state = transition(state, WorkflowEvent.INSPECTION_SUCCEEDED)
    assert state.can_mesh and state.can_edit_parameters
    state = transition(state, WorkflowEvent.MESH_STARTED)
    assert state.stage is WorkflowStage.MESHING
    assert not state.can_edit_parameters and state.can_cancel
    state = transition(state, WorkflowEvent.MESH_SUCCEEDED)
    assert state.can_solve
    state = transition(state, WorkflowEvent.SOLVE_STARTED)
    assert not state.can_edit_parameters


def test_failures_and_cancel_recover_without_enabling_invalid_downstream():
    state = transition(initial_workflow_state(), WorkflowEvent.MODEL_SELECTED)
    state = transition(state, WorkflowEvent.INSPECTION_SUCCEEDED)
    state = transition(state, WorkflowEvent.MESH_STARTED)
    state = transition(state, WorkflowEvent.MESH_FAILED, "网格生成失败")
    assert state.stage is WorkflowStage.FAILED
    assert state.failure_message == "网格生成失败"
    assert not state.can_solve
    recovered = transition(state, WorkflowEvent.RESET)
    assert recovered.stage is WorkflowStage.GEOMETRY_READY

    running = transition(
        recovered, WorkflowEvent.MESH_STARTED,
    )
    cancelled = transition(running, WorkflowEvent.CANCEL)
    assert cancelled.stage is WorkflowStage.CANCELLED
    assert transition(cancelled, WorkflowEvent.RESET).can_mesh


def test_illegal_transition_is_rejected():
    with pytest.raises(WorkflowTransitionError):
        transition(initial_workflow_state(), WorkflowEvent.SOLVE_STARTED)
