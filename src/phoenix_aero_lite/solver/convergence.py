"""Deterministic, versioned convergence classification for SU2 histories."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from statistics import median
from types import MappingProxyType
from typing import Mapping

from phoenix_aero_lite.models.evidence import ConvergenceStatus
from phoenix_aero_lite.solver.su2_history import Su2History


@dataclass(frozen=True, slots=True)
class ConvergenceThresholds:
    """Legacy-compatible explicit numerical thresholds."""

    min_iterations: int
    residual_target: float
    residual_reduction_orders: float
    recent_window: int
    coefficient_span_tolerance: float
    divergence_rise_orders: float
    stagnation_progress_orders: float
    max_iterations: int

    def __post_init__(self) -> None:
        _validate_thresholds(self)


@dataclass(frozen=True, slots=True)
class ConvergencePolicy:
    """Named and versioned decision policy persisted with each classification."""

    preset: str
    policy_version: str
    min_iterations: int
    residual_target: float
    residual_reduction_orders: float
    recent_window: int
    coefficient_span_tolerance: float
    divergence_rise_orders: float
    stagnation_progress_orders: float
    max_iterations: int
    cl_span_tolerance: float = 0.01
    cd_span_tolerance: float = 0.01
    likely_residual_reduction_orders: float = 1.5
    oscillation_reversal_fraction: float = 0.6
    oscillation_net_drift_fraction: float = 0.35
    coefficient_absolute_limit: float = 100.0

    def __post_init__(self) -> None:
        _validate_thresholds(self)
        numeric = (
            self.cl_span_tolerance,
            self.cd_span_tolerance,
            self.likely_residual_reduction_orders,
            self.oscillation_reversal_fraction,
            self.oscillation_net_drift_fraction,
            self.coefficient_absolute_limit,
        )
        if (
            self.preset not in {"preview", "standard", "fine", "benchmark"}
            or not self.policy_version
            or any(not math.isfinite(value) for value in numeric)
            or self.likely_residual_reduction_orders < 0
            or self.cl_span_tolerance < 0
            or self.cd_span_tolerance < 0
            or not 0 < self.oscillation_reversal_fraction <= 1
            or not 0 <= self.oscillation_net_drift_fraction <= 1
            or self.coefficient_absolute_limit <= 0
        ):
            raise ValueError("CONVERGENCE_POLICY_INVALID")


def convergence_policy(preset: str, max_iterations: int) -> ConvergencePolicy:
    """Return policy v1 without hidden dependence on GUI or process state."""

    if (
        not isinstance(preset, str)
        or not isinstance(max_iterations, int)
        or isinstance(max_iterations, bool)
        or max_iterations <= 0
    ):
        raise ValueError("CONVERGENCE_POLICY_INVALID")
    normalized = preset.strip().casefold()
    targets = {
        "preview": -6.0,
        "standard": -6.0,
        "fine": -6.5,
        "benchmark": -7.0,
    }
    if normalized not in targets:
        raise ValueError("CONVERGENCE_POLICY_UNKNOWN")
    recent = max(2, min(20, max_iterations // 2 or 2))
    return ConvergencePolicy(
        preset=normalized,
        policy_version="1",
        min_iterations=min(50, max_iterations),
        residual_target=targets[normalized],
        residual_reduction_orders=3.0,
        recent_window=recent,
        coefficient_span_tolerance=0.01,
        divergence_rise_orders=2.0,
        stagnation_progress_orders=0.02,
        max_iterations=max_iterations,
        cl_span_tolerance=0.01,
        cd_span_tolerance=0.01,
        likely_residual_reduction_orders=1.5,
        oscillation_reversal_fraction=0.6,
        oscillation_net_drift_fraction=0.35,
        coefficient_absolute_limit=100.0,
    )


@dataclass(frozen=True, slots=True)
class ConvergenceExecution:
    """Process and history-integrity evidence, separate from numerical behavior."""

    process_status: str = "succeeded"
    exit_code: int | None = 0
    history_complete: bool = True
    integrity_error: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            "succeeded",
            "nonzero_exit",
            "start_failed",
            "timed_out",
            "cancelled",
            "interrupted",
        }
        if (
            self.process_status not in allowed
            or (
                self.exit_code is not None
                and (
                    not isinstance(self.exit_code, int)
                    or isinstance(self.exit_code, bool)
                )
            )
            or not isinstance(self.history_complete, bool)
            or (
                self.integrity_error is not None
                and (
                    not isinstance(self.integrity_error, str)
                    or not self.integrity_error
                )
            )
        ):
            raise ValueError("CONVERGENCE_EXECUTION_INVALID")


@dataclass(frozen=True, slots=True)
class ConvergenceResult:
    """One auditable classification and its final reported values."""

    status: ConvergenceStatus
    reason_code: str
    iterations_observed: int
    final_residual: float | None
    final_cl: float | None
    final_cd: float | None
    thresholds: ConvergenceThresholds | ConvergencePolicy
    execution: ConvergenceExecution = field(default_factory=ConvergenceExecution)
    policy_version: str = "legacy"
    diagnostics: Mapping[str, float | int | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def classify_convergence(
    history: Su2History,
    thresholds: ConvergenceThresholds | ConvergencePolicy,
    *,
    execution: ConvergenceExecution | None = None,
) -> ConvergenceResult:
    """Classify numerical evidence without equating process completion with validity."""

    evidence = execution or ConvergenceExecution()
    if evidence.integrity_error:
        return _result(
            ConvergenceStatus.INVALID,
            evidence.integrity_error,
            history if isinstance(history, Su2History) else None,
            thresholds,
            evidence,
        )

    if evidence.process_status in {
        "cancelled",
        "timed_out",
        "start_failed",
        "interrupted",
        "nonzero_exit",
    }:
        return _result(
            ConvergenceStatus.INCOMPLETE,
            f"SOLVER_{evidence.process_status.upper()}",
            history if isinstance(history, Su2History) else None,
            thresholds,
            evidence,
        )

    if not isinstance(history, Su2History) or not history.samples:
        return _result(
            ConvergenceStatus.INVALID,
            "HISTORY_EMPTY",
            history if isinstance(history, Su2History) else None,
            thresholds,
            evidence,
        )

    samples = history.samples
    residuals = [sample.rms_pressure for sample in samples]
    coefficients = [
        value
        for sample in samples
        for value in (sample.cl, sample.cd)
        if value is not None
    ]
    if any(not math.isfinite(value) for value in (*residuals, *coefficients)):
        return _result(
            ConvergenceStatus.DIVERGED,
            "NUMERICAL_VALUE_NONFINITE",
            history,
            thresholds,
            evidence,
        )
    if residuals[-1] - min(residuals) >= thresholds.divergence_rise_orders:
        return _result(
            ConvergenceStatus.DIVERGED,
            "RESIDUAL_EXPLOSION",
            history,
            thresholds,
            evidence,
        )
    absolute_limit = getattr(thresholds, "coefficient_absolute_limit", 100.0)
    if coefficients and max(abs(value) for value in coefficients) >= absolute_limit:
        return _result(
            ConvergenceStatus.DIVERGED,
            "COEFFICIENT_EXPLOSION",
            history,
            thresholds,
            evidence,
        )
    if not evidence.history_complete:
        return _result(
            ConvergenceStatus.INCOMPLETE,
            "HISTORY_PARTIAL",
            history,
            thresholds,
            evidence,
        )

    count = len(samples)
    recent = samples[-thresholds.recent_window :]
    coefficient_stable = _coefficients_stable(recent, thresholds)
    if _coefficients_oscillating(recent, thresholds):
        return _result(
            ConvergenceStatus.OSCILLATING,
            "COEFFICIENT_OSCILLATION",
            history,
            thresholds,
            evidence,
        )

    reduction = residuals[0] - residuals[-1]
    if (
        count >= thresholds.min_iterations
        and residuals[-1] <= thresholds.residual_target
        and reduction >= thresholds.residual_reduction_orders
        and coefficient_stable
    ):
        return _result(
            ConvergenceStatus.CONVERGED,
            "TARGET_AND_FORCE_PLATEAU",
            history,
            thresholds,
            evidence,
        )

    if count >= thresholds.recent_window * 2:
        earlier = residuals[
            -2 * thresholds.recent_window : -thresholds.recent_window
        ]
        latest = residuals[-thresholds.recent_window :]
        progress = median(earlier) - median(latest)
        if progress < thresholds.stagnation_progress_orders:
            return _result(
                ConvergenceStatus.STAGNATED,
                "RESIDUAL_STAGNATION",
                history,
                thresholds,
                evidence,
            )

    likely_reduction = getattr(
        thresholds,
        "likely_residual_reduction_orders",
        max(0.5, thresholds.residual_reduction_orders / 2),
    )
    if (
        count >= thresholds.min_iterations
        and reduction >= likely_reduction
        and coefficient_stable
    ):
        return _result(
            ConvergenceStatus.LIKELY_CONVERGED,
            "FORCE_PLATEAU_WITH_MEANINGFUL_RESIDUAL_REDUCTION",
            history,
            thresholds,
            evidence,
        )

    if samples[-1].iteration + 1 >= thresholds.max_iterations:
        return _result(
            ConvergenceStatus.INCOMPLETE,
            "ITERATION_LIMIT_REACHED",
            history,
            thresholds,
            evidence,
        )
    return _result(
        ConvergenceStatus.NOT_EVALUATED,
        "MORE_ITERATIONS_REQUIRED",
        history,
        thresholds,
        evidence,
    )


def _coefficients_stable(
    samples: tuple | list,
    thresholds: ConvergenceThresholds | ConvergencePolicy,
) -> bool:
    cl_tolerance = getattr(
        thresholds, "cl_span_tolerance", thresholds.coefficient_span_tolerance
    )
    cd_tolerance = getattr(
        thresholds, "cd_span_tolerance", thresholds.coefficient_span_tolerance
    )
    return bool(samples) and all(
        sample.cl is not None
        and sample.cd is not None
        and math.isfinite(sample.cl)
        and math.isfinite(sample.cd)
        for sample in samples
    ) and all(
        max(values) - min(values) <= tolerance
        for values, tolerance in (
            ([sample.cl for sample in samples], cl_tolerance),
            ([sample.cd for sample in samples], cd_tolerance),
        )
    )


def _coefficients_oscillating(
    samples: tuple | list,
    thresholds: ConvergenceThresholds | ConvergencePolicy,
) -> bool:
    if len(samples) < 3:
        return False
    reversal_target = getattr(thresholds, "oscillation_reversal_fraction", 0.6)
    net_drift_fraction = getattr(
        thresholds, "oscillation_net_drift_fraction", 0.35
    )
    absolute_limit = getattr(thresholds, "coefficient_absolute_limit", 100.0)
    for values, span_tolerance in (
        (
            [sample.cl for sample in samples],
            getattr(
                thresholds,
                "cl_span_tolerance",
                thresholds.coefficient_span_tolerance,
            ),
        ),
        (
            [sample.cd for sample in samples],
            getattr(
                thresholds,
                "cd_span_tolerance",
                thresholds.coefficient_span_tolerance,
            ),
        ),
    ):
        if any(value is None or not math.isfinite(value) for value in values):
            continue
        finite = [float(value) for value in values if value is not None]
        span = max(finite) - min(finite)
        if not span_tolerance < span < absolute_limit:
            continue
        differences = [
            right - left for left, right in zip(finite, finite[1:], strict=False)
        ]
        nonzero = [value for value in differences if abs(value) > 1e-12]
        if len(nonzero) < 2:
            continue
        reversals = sum(
            left * right < 0
            for left, right in zip(nonzero, nonzero[1:], strict=False)
        )
        reversal_fraction = reversals / (len(nonzero) - 1)
        net_drift = abs(finite[-1] - finite[0])
        if (
            reversal_fraction >= reversal_target
            and net_drift <= span * net_drift_fraction
        ):
            return True
    return False


def _validate_thresholds(thresholds: object) -> None:
    integer_values = (
        getattr(thresholds, "min_iterations"),
        getattr(thresholds, "recent_window"),
        getattr(thresholds, "max_iterations"),
    )
    numeric = (
        getattr(thresholds, "residual_target"),
        getattr(thresholds, "residual_reduction_orders"),
        getattr(thresholds, "coefficient_span_tolerance"),
        getattr(thresholds, "divergence_rise_orders"),
        getattr(thresholds, "stagnation_progress_orders"),
    )
    if (
        any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in integer_values
        )
        or any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for value in numeric
        )
        or any(value <= 0 for value in integer_values)
        or any(not math.isfinite(value) for value in numeric)
        or getattr(thresholds, "residual_reduction_orders") < 0
        or getattr(thresholds, "coefficient_span_tolerance") < 0
        or getattr(thresholds, "divergence_rise_orders") <= 0
        or getattr(thresholds, "stagnation_progress_orders") < 0
    ):
        raise ValueError("CONVERGENCE_THRESHOLDS_INVALID")


def _result(
    status: ConvergenceStatus,
    reason_code: str,
    history: Su2History | None,
    thresholds: ConvergenceThresholds | ConvergencePolicy,
    execution: ConvergenceExecution,
) -> ConvergenceResult:
    samples = history.samples if history is not None else ()
    final = samples[-1] if samples else None
    residuals = [sample.rms_pressure for sample in samples]
    recent = samples[-thresholds.recent_window :] if samples else ()
    cl_values = [sample.cl for sample in recent if sample.cl is not None]
    cd_values = [sample.cd for sample in recent if sample.cd is not None]
    recent_progress = None
    if len(samples) >= thresholds.recent_window * 2:
        earlier = residuals[
            -2 * thresholds.recent_window : -thresholds.recent_window
        ]
        latest = residuals[-thresholds.recent_window :]
        recent_progress = median(earlier) - median(latest)
    diagnostics = {
        "initial_residual": residuals[0] if residuals else None,
        "residual_reduction_orders": (
            residuals[0] - residuals[-1] if residuals else None
        ),
        "recent_residual_progress": recent_progress,
        "cl_recent_span": max(cl_values) - min(cl_values) if cl_values else None,
        "cd_recent_span": max(cd_values) - min(cd_values) if cd_values else None,
    }
    return ConvergenceResult(
        status=status,
        reason_code=reason_code,
        iterations_observed=len(samples),
        final_residual=final.rms_pressure if final else None,
        final_cl=final.cl if final else None,
        final_cd=final.cd if final else None,
        thresholds=thresholds,
        execution=execution,
        policy_version=getattr(thresholds, "policy_version", "legacy"),
        diagnostics=diagnostics,
    )
