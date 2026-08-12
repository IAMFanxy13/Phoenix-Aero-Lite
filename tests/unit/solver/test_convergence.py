from __future__ import annotations

from dataclasses import replace

from phoenix_aero_lite.solver.convergence import (
    ConvergenceExecution,
    ConvergencePolicy,
    ConvergenceStatus,
    ConvergenceThresholds,
    classify_convergence,
    convergence_policy,
)
from phoenix_aero_lite.solver.su2_history import HistorySample, Su2History


def _history(
    residuals: list[float],
    cls: list[float] | None = None,
    cds: list[float] | None = None,
) -> Su2History:
    lift = cls or [0.5] * len(residuals)
    drag = cds or [0.03] * len(residuals)
    return Su2History(
        source_path=None,
        samples=tuple(
            HistorySample(i, value, value, value, drag[i], lift[i], 0.0, 0.0, 0.0)
            for i, value in enumerate(residuals)
        ),
    )


def _thresholds(max_iterations: int = 100) -> ConvergenceThresholds:
    return ConvergenceThresholds(
        min_iterations=5,
        residual_target=-5.0,
        residual_reduction_orders=3.0,
        recent_window=3,
        coefficient_span_tolerance=0.01,
        divergence_rise_orders=2.0,
        stagnation_progress_orders=0.05,
        max_iterations=max_iterations,
    )


def test_classifies_converged_and_preserves_thresholds():
    result = classify_convergence(
        _history([-1, -2, -3, -4, -5.1, -5.2], [0.5, 0.51, 0.5, 0.501, 0.5, 0.499]),
        _thresholds(),
    )
    assert result.status is ConvergenceStatus.CONVERGED
    assert result.thresholds.residual_target == -5.0
    assert result.final_cl == 0.499


def test_distinguishes_running_diverged_stagnated_and_max_iterations():
    assert classify_convergence(
        _history([-1, -2]), _thresholds()
    ).status is ConvergenceStatus.RUNNING
    assert classify_convergence(
        _history([-3, -2, -0.5, 0]), _thresholds()
    ).status is ConvergenceStatus.DIVERGED
    assert classify_convergence(
        _history([-2, -2.01, -2.02, -2.02, -2.03, -2.03]),
        _thresholds(),
    ).status is ConvergenceStatus.STAGNATED
    assert classify_convergence(
        _history([-1, -2, -3, -4]), _thresholds(max_iterations=4)
    ).status is ConvergenceStatus.MAX_ITERATIONS


def test_empty_history_is_invalid():
    result = classify_convergence(
        Su2History(source_path=None, samples=()), _thresholds()
    )
    assert result.status is ConvergenceStatus.INVALID


def test_preview_policy_is_versioned_and_preserves_approved_air_thresholds():
    policy = convergence_policy("preview", 150)

    assert isinstance(policy, ConvergencePolicy)
    assert policy.policy_version == "1"
    assert policy.preset == "preview"
    assert policy.recent_window == 20
    assert policy.residual_target == -6.0
    assert policy.residual_reduction_orders == 3.0
    assert policy.coefficient_span_tolerance == 0.01
    assert policy.cl_span_tolerance == 0.01
    assert policy.cd_span_tolerance == 0.01
    assert policy.divergence_rise_orders == 2.0
    assert policy.stagnation_progress_orders == 0.02
    assert policy.oscillation_net_drift_fraction == 0.35
    assert policy.max_iterations == 150


def test_stable_coefficients_with_reduction_below_strict_target_are_likely_converged():
    residuals = [-1.0, -1.5, -2.0, -2.5, -3.0, -3.3, -3.45, -3.55]
    result = classify_convergence(_history(residuals), _thresholds())

    assert result.status is ConvergenceStatus.LIKELY_CONVERGED
    assert result.reason_code == "FORCE_PLATEAU_WITH_MEANINGFUL_RESIDUAL_REDUCTION"


def test_bounded_sustained_coefficient_reversals_are_oscillating():
    residuals = [-1.0, -1.3, -1.6, -1.9, -2.2, -2.5, -2.8, -3.1]
    lift = [0.50, 0.56, 0.49, 0.57, 0.48, 0.58, 0.47, 0.59]
    result = classify_convergence(_history(residuals, lift), _thresholds())

    assert result.status is ConvergenceStatus.OSCILLATING
    assert result.reason_code == "COEFFICIENT_OSCILLATION"


def test_oscillation_uses_the_quantity_specific_span_threshold():
    policy = replace(
        convergence_policy("preview", 100),
        min_iterations=5,
        recent_window=3,
        cl_span_tolerance=0.2,
    )
    residuals = [-1.0, -1.4, -1.8, -2.2, -2.6, -3.0]
    lift = [0.50, 0.56, 0.49, 0.57, 0.48, 0.58]

    result = classify_convergence(_history(residuals, lift), policy)

    assert result.status is ConvergenceStatus.LIKELY_CONVERGED


def test_nonfinite_or_exploding_numerics_are_diverged():
    nonfinite = classify_convergence(
        _history([-1.0, -2.0, float("nan")]), _thresholds()
    )
    coefficient_explosion = classify_convergence(
        _history([-1.0, -2.0, -3.0], [0.5, 0.6, 1_000.0]), _thresholds()
    )

    assert nonfinite.status is ConvergenceStatus.DIVERGED
    assert nonfinite.reason_code == "NUMERICAL_VALUE_NONFINITE"
    assert coefficient_explosion.status is ConvergenceStatus.DIVERGED
    assert coefficient_explosion.reason_code == "COEFFICIENT_EXPLOSION"


def test_integrity_error_is_invalid_before_any_numerical_promotion():
    result = classify_convergence(
        _history([-1.0, -2.0, -3.0]),
        _thresholds(),
        execution=ConvergenceExecution(integrity_error="HISTORY_COLUMNS_MISSING"),
    )

    assert result.status is ConvergenceStatus.INVALID
    assert result.reason_code == "HISTORY_COLUMNS_MISSING"


def test_interrupted_process_states_and_partial_nonzero_exit_are_incomplete():
    history = _history([-1.0, -2.0, -3.0])
    for process_status in ("cancelled", "timed_out", "start_failed", "interrupted"):
        result = classify_convergence(
            history,
            _thresholds(),
            execution=ConvergenceExecution(
                process_status=process_status,
                exit_code=None,
                history_complete=False,
            ),
        )
        assert result.status is ConvergenceStatus.INCOMPLETE
        assert result.reason_code == f"SOLVER_{process_status.upper()}"

    nonzero = classify_convergence(
        history,
        _thresholds(),
        execution=ConvergenceExecution(
            process_status="nonzero_exit",
            exit_code=2,
            history_complete=False,
        ),
    )
    assert nonzero.status is ConvergenceStatus.INCOMPLETE
    assert nonzero.reason_code == "SOLVER_NONZERO_EXIT"


def test_successful_process_does_not_imply_convergence():
    result = classify_convergence(
        _history([-2, -2.01, -2.02, -2.02, -2.03, -2.03]),
        _thresholds(),
        execution=ConvergenceExecution(
            process_status="succeeded", exit_code=0, history_complete=True
        ),
    )

    assert result.status is ConvergenceStatus.STAGNATED
    assert result.diagnostics["recent_residual_progress"] is not None
    assert result.diagnostics["cl_recent_span"] == 0.0
    assert result.diagnostics["cd_recent_span"] == 0.0


def test_truncated_history_cannot_be_promoted_even_if_visible_window_is_stable():
    result = classify_convergence(
        _history([-1, -2, -3, -4, -5.1, -5.2], [0.5] * 6),
        _thresholds(),
        execution=ConvergenceExecution(
            process_status="succeeded", exit_code=0, history_complete=False
        ),
    )

    assert result.status is ConvergenceStatus.INCOMPLETE
    assert result.reason_code == "HISTORY_PARTIAL"
