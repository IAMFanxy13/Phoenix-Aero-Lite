from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from phoenix_aero_lite.models.parameters import (
    AircraftParameters,
    CaseParameters,
    FlowParameters,
    MeshMode,
    MeshParameters,
    OutputParameters,
    ReferenceParameters,
    SolverParameters,
)
from phoenix_aero_lite.postprocess.aero_summary import (
    AeroSummaryError,
    body_to_wind_coefficients,
    summarize_aerodynamics,
)
from phoenix_aero_lite.solver.convergence import (
    ConvergenceResult,
    ConvergenceStatus,
    ConvergenceThresholds,
)
from phoenix_aero_lite.solver.su2_history import HistorySample


def _parameters() -> CaseParameters:
    return CaseParameters(
        flow=FlowParameters(20.0, 1.225, 1.7894e-5, 10.0),
        reference=ReferenceParameters(2.0, 0.5),
        aircraft=AircraftParameters(10.0),
        mesh=MeshParameters(MeshMode.PREVIEW, 0.5),
        solver=SolverParameters(100),
        output=OutputParameters(Path("case")),
    )


def _convergence(status: ConvergenceStatus) -> ConvergenceResult:
    return ConvergenceResult(
        status=status,
        reason_code="test",
        iterations_observed=50,
        final_residual=-6.0,
        final_cl=0.5,
        final_cd=0.05,
        thresholds=ConvergenceThresholds(5, -5, 3, 3, 0.01, 2, 0.05, 100),
    )


def _sample() -> HistorySample:
    return HistorySample(49, -6, -6, -6, 0.05, 0.5, 0.1, 0.0, 0.6)


def test_converts_coefficients_to_forces_weight_and_margin_with_sources():
    summary = summarize_aerodynamics(
        _parameters(), _convergence(ConvergenceStatus.CONVERGED), _sample()
    )
    q = 0.5 * 1.225 * 20.0**2
    assert summary.valid
    assert summary.dynamic_pressure.value == pytest.approx(q)
    assert summary.lift.value == pytest.approx(0.5 * q * 2.0)
    assert summary.drag.value == pytest.approx(0.05 * q * 2.0)
    assert summary.weight.value == pytest.approx(10 * 9.80665)
    assert summary.lift_margin.value == pytest.approx(
        summary.lift.value - summary.weight.value
    )
    assert summary.meets_weight_requirement is True
    assert summary.lift.unit == "N"
    assert "CL" in summary.lift.source
    json.loads(summary.to_json())


def test_rotates_body_coefficients_at_angle_of_attack():
    drag, lift = body_to_wind_coefficients(1.0, 0.0, 90.0)
    assert drag == pytest.approx(0.0, abs=1e-12)
    assert lift == pytest.approx(-1.0)


def test_unconverged_result_is_invalid_and_never_claims_weight_pass():
    summary = summarize_aerodynamics(
        _parameters(), _convergence(ConvergenceStatus.STAGNATED), _sample()
    )
    assert not summary.valid
    assert summary.cl.value == pytest.approx(0.5)
    assert summary.cd.value == pytest.approx(0.05)
    assert summary.lift is None
    assert summary.lift_margin is None
    assert summary.meets_weight_requirement is None
    assert summary.reason_code == "CFD_NOT_CONVERGED"


def test_missing_reference_and_nonfinite_values_are_rejected():
    parameters = _parameters()
    invalid = CaseParameters(
        flow=parameters.flow,
        reference=ReferenceParameters(0.0, 0.5),
        aircraft=parameters.aircraft,
        mesh=parameters.mesh,
        solver=parameters.solver,
        output=parameters.output,
    )
    with pytest.raises(AeroSummaryError, match="AERO_INPUT_INVALID"):
        summarize_aerodynamics(
            invalid, _convergence(ConvergenceStatus.CONVERGED), _sample()
        )
    bad = HistorySample(1, -5, -5, -5, math.nan, 0.5, 0, 0, 0)
    with pytest.raises(AeroSummaryError, match="AERO_COEFFICIENT_INVALID"):
        summarize_aerodynamics(
            parameters, _convergence(ConvergenceStatus.CONVERGED), bad
        )


def test_rejects_sample_from_a_different_convergence_result():
    sample = _sample()
    mismatched = HistorySample(
        sample.iteration,
        sample.rms_pressure,
        sample.rms_tke,
        sample.rms_omega,
        0.06,
        sample.cl,
        sample.force_x,
        sample.force_y,
        sample.force_z,
    )
    with pytest.raises(AeroSummaryError, match="AERO_RESULT_MISMATCH"):
        summarize_aerodynamics(
            _parameters(),
            _convergence(ConvergenceStatus.CONVERGED),
            mismatched,
        )
