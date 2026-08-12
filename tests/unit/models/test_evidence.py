from __future__ import annotations

import json

import pytest

from phoenix_aero_lite.models.evidence import (
    ConvergenceStatus,
    EvidenceStatus,
    ExecutionStatus,
    QuantityEvidence,
    ScientificEvidence,
    ScientificUseLevel,
    ValidationLevel,
)


def _quantity(
    name: str,
    *,
    status: EvidenceStatus,
    value: float | None,
    diagnostic: bool,
    trend: bool,
    engineering: bool,
) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_name=name,
        value=value,
        unit="1",
        source="synthetic state-machine fixture",
        calculation_method="literal test input",
        evidence_status=status,
        convergence_status=ConvergenceStatus.LIKELY_CONVERGED,
        validation_level=ValidationLevel.L1,
        user_overridden=False,
        usable_for_diagnostic=diagnostic,
        usable_for_trend=trend,
        usable_for_engineering=engineering,
        blocking_reasons=("GRID_STUDY_MISSING",),
        warnings=(),
    )


def test_scientific_states_are_independent_and_serialize_as_strict_json():
    cl = _quantity(
        "CL",
        status=EvidenceStatus.COMPUTED,
        value=0.42,
        diagnostic=True,
        trend=True,
        engineering=False,
    )
    cd = _quantity(
        "CD",
        status=EvidenceStatus.ESTIMATED,
        value=0.08,
        diagnostic=True,
        trend=False,
        engineering=False,
    )
    evidence = ScientificEvidence(
        execution_status=ExecutionStatus.COMPLETED,
        convergence_status=ConvergenceStatus.LIKELY_CONVERGED,
        scientific_use_level=ScientificUseLevel.TREND_ONLY,
        validation_level=ValidationLevel.L1,
        quantities={"CL": cl, "CD": cd},
        blocking_reasons=("GRID_STUDY_MISSING",),
        warnings=("synthetic fixture only",),
    )

    payload = evidence.to_dict()

    assert payload["execution_status"] == "completed"
    assert payload["convergence_status"] == "likely_converged"
    assert payload["scientific_use_level"] == "trend_only"
    assert payload["validation_level"] == "L1"
    assert payload["quantities"]["CL"]["evidence_status"] == "computed"
    assert payload["quantities"]["CD"]["evidence_status"] == "estimated"
    assert payload["quantities"]["CL"]["usable_for_engineering"] is False
    json.dumps(payload, allow_nan=False)
    assert ScientificEvidence.from_dict(payload) == evidence


def test_missing_legacy_evidence_defaults_to_no_scientific_permission():
    evidence = ScientificEvidence.from_dict({})

    assert evidence.execution_status is ExecutionStatus.DRAFT
    assert evidence.convergence_status is ConvergenceStatus.NOT_EVALUATED
    assert evidence.scientific_use_level is ScientificUseLevel.INVALID
    assert evidence.validation_level is None
    assert evidence.quantities == {}


@pytest.mark.parametrize(
    "quantity",
    [
        lambda: _quantity(
            "CL",
            status=EvidenceStatus.MISSING,
            value=0.5,
            diagnostic=False,
            trend=False,
            engineering=False,
        ),
        lambda: _quantity(
            "CL",
            status=EvidenceStatus.COMPUTED,
            value=float("nan"),
            diagnostic=True,
            trend=False,
            engineering=False,
        ),
        lambda: _quantity(
            "CL",
            status=EvidenceStatus.COMPUTED,
            value=0.5,
            diagnostic=False,
            trend=False,
            engineering=True,
        ),
    ],
)
def test_quantity_evidence_rejects_false_or_nonfinite_promotion(quantity):
    with pytest.raises(ValueError, match="QUANTITY_EVIDENCE_INVALID"):
        quantity()


def test_all_required_enum_values_are_stable():
    assert {item.value for item in ExecutionStatus} == {
        "draft",
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    }
    assert {item.value for item in ConvergenceStatus} == {
        "not_evaluated",
        "converged",
        "likely_converged",
        "stagnated",
        "oscillating",
        "diverged",
        "incomplete",
        "invalid",
    }
    assert {item.value for item in ScientificUseLevel} == {
        "invalid",
        "diagnostic_only",
        "trend_only",
        "engineering_comparison",
        "externally_validated",
    }
    assert {item.value for item in ValidationLevel} == {
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    }
    assert {item.value for item in EvidenceStatus} == {
        "unknown",
        "estimated",
        "computed",
        "measured",
        "verified",
        "missing",
        "invalid",
    }


def test_case_cannot_claim_engineering_use_without_engineering_cl_and_cd():
    with pytest.raises(ValueError, match="SCIENTIFIC_EVIDENCE_INVALID"):
        ScientificEvidence(
            execution_status=ExecutionStatus.COMPLETED,
            convergence_status=ConvergenceStatus.CONVERGED,
            scientific_use_level=ScientificUseLevel.ENGINEERING_COMPARISON,
            validation_level=ValidationLevel.L3,
            quantities={},
        )
