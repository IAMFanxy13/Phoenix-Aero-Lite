from types import SimpleNamespace

import pytest

from phoenix_aero_lite.models.evidence import (
    EvidenceStatus,
    ScientificUseLevel,
    ValidationLevel,
)
from phoenix_aero_lite.solver.convergence import ConvergenceStatus
from phoenix_aero_lite.solver.credibility import (
    CredibilityLevel,
    assess_credibility,
)


def convergence(status, *, cl=0.6, cd=0.05):
    return SimpleNamespace(
        status=status,
        reason_code=f"{status.value.upper()}_REASON",
        final_cl=cl,
        final_cd=cd,
    )


def validated_mesh():
    return {
        "negative_quality_count": 0,
        "non_manifold_face_count": 0,
        "physical_group_presence": {
            "fluid": True,
            "aircraft": True,
            "farfield": True,
        },
        "near_wall": {
            "required": True,
            "present": True,
            "drag_fidelity": "validated_near_wall_layers",
            "y_plus": {
                "value": 1.0,
                "status": "verified",
                "source": "resolved wall field",
            },
        },
    }


def test_converged_validated_result_is_reliable():
    result = assess_credibility(
        convergence(ConvergenceStatus.CONVERGED),
        validated_mesh(),
        validation_level=ValidationLevel.L3,
    )

    assert result.level is CredibilityLevel.RELIABLE
    assert result.coefficients_usable is True
    assert result.reason_codes == ("CONVERGED_WITH_VALIDATED_MESH",)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (ConvergenceStatus.STAGNATED, "CONVERGENCE_STAGNATED"),
        (ConvergenceStatus.MAX_ITERATIONS, "ITERATION_LIMIT_REACHED"),
    ],
)
def test_unconverged_finite_result_is_caution(status, reason):
    result = assess_credibility(convergence(status), validated_mesh())

    assert result.level is CredibilityLevel.CAUTION
    assert result.coefficients_usable is False
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "status", [ConvergenceStatus.DIVERGED, ConvergenceStatus.INVALID]
)
def test_diverged_or_invalid_result_is_invalid(status):
    result = assess_credibility(convergence(status), validated_mesh())

    assert result.level is CredibilityLevel.INVALID
    assert result.coefficients_usable is False


def test_preview_mesh_caps_converged_result_at_caution():
    mesh = validated_mesh()
    mesh["near_wall"] = {
        "required": False,
        "present": False,
        "drag_fidelity": "preview_only",
    }

    result = assess_credibility(convergence(ConvergenceStatus.CONVERGED), mesh)

    assert result.level is CredibilityLevel.CAUTION
    assert "MESH_PREVIEW_ONLY" in result.reason_codes


def test_missing_or_nonfinite_coefficients_are_invalid():
    result = assess_credibility(
        convergence(ConvergenceStatus.CONVERGED, cl=None), validated_mesh()
    )

    assert result.level is CredibilityLevel.INVALID
    assert result.reason_codes == ("COEFFICIENTS_NONFINITE_OR_MISSING",)


def test_broken_mesh_evidence_is_invalid():
    mesh = validated_mesh()
    mesh["non_manifold_face_count"] = 1

    result = assess_credibility(convergence(ConvergenceStatus.CONVERGED), mesh)

    assert result.level is CredibilityLevel.INVALID
    assert "MESH_NON_MANIFOLD" in result.reason_codes


def test_likely_converged_coefficients_are_trend_only_not_engineering():
    result = assess_credibility(
        convergence(ConvergenceStatus.LIKELY_CONVERGED),
        validated_mesh(),
        validation_level=ValidationLevel.L1,
    )

    assert result.scientific_evidence.scientific_use_level is ScientificUseLevel.TREND_ONLY
    for name in ("CL", "CD"):
        quantity = result.scientific_evidence.quantities[name]
        assert quantity.usable_for_diagnostic is True
        assert quantity.usable_for_trend is True
        assert quantity.usable_for_engineering is False
    assert result.coefficients_usable is False


def test_stagnated_coefficients_are_diagnostic_only():
    result = assess_credibility(
        convergence(ConvergenceStatus.STAGNATED), validated_mesh()
    )

    assert (
        result.scientific_evidence.scientific_use_level
        is ScientificUseLevel.DIAGNOSTIC_ONLY
    )
    cl = result.scientific_evidence.quantities["CL"]
    assert cl.usable_for_diagnostic is True
    assert cl.usable_for_trend is False
    assert cl.usable_for_engineering is False


def test_engineering_permission_requires_l3_and_verified_y_plus():
    low_validation = assess_credibility(
        convergence(ConvergenceStatus.CONVERGED),
        validated_mesh(),
        validation_level=ValidationLevel.L1,
    )
    missing_y_plus_mesh = validated_mesh()
    del missing_y_plus_mesh["near_wall"]["y_plus"]
    missing_y_plus = assess_credibility(
        convergence(ConvergenceStatus.CONVERGED),
        missing_y_plus_mesh,
        validation_level=ValidationLevel.L3,
    )

    assert low_validation.coefficients_usable is False
    assert "VALIDATION_EVIDENCE_BELOW_L3" in low_validation.reason_codes
    assert missing_y_plus.coefficients_usable is False
    assert "Y_PLUS_EVIDENCE_MISSING" in missing_y_plus.reason_codes


def test_computed_y_plus_is_not_misreported_as_missing():
    mesh = validated_mesh()
    mesh["near_wall"]["y_plus"] = {
        "value": 1.1,
        "status": "computed",
        "source": "SU2 solved wall field",
    }

    result = assess_credibility(
        convergence(ConvergenceStatus.CONVERGED),
        mesh,
        validation_level=ValidationLevel.L3,
    )

    assert "Y_PLUS_EVIDENCE_NOT_VERIFIED" in result.reason_codes
    assert "Y_PLUS_EVIDENCE_MISSING" not in result.reason_codes
    y_plus = result.scientific_evidence.quantities["y_plus"]
    assert y_plus.evidence_status is EvidenceStatus.COMPUTED
    assert y_plus.blocking_reasons == ("Y_PLUS_EVIDENCE_NOT_VERIFIED",)


def test_cl_and_cd_keep_independent_evidence_when_one_is_missing():
    result = assess_credibility(
        convergence(ConvergenceStatus.CONVERGED, cl=0.6, cd=None),
        validated_mesh(),
        validation_level=ValidationLevel.L3,
    )

    assert (
        result.scientific_evidence.quantities["CL"].evidence_status
        is EvidenceStatus.COMPUTED
    )
    assert (
        result.scientific_evidence.quantities["CD"].evidence_status
        is EvidenceStatus.MISSING
    )
    assert result.coefficients_usable is False
