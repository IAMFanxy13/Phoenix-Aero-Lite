"""Scientific-use assessment kept separate from process execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping

from phoenix_aero_lite.models.evidence import (
    ConvergenceStatus,
    EvidenceStatus,
    ExecutionStatus,
    QuantityEvidence,
    ScientificEvidence,
    ScientificUseLevel,
    ValidationLevel,
)
from phoenix_aero_lite.solver.convergence import ConvergenceResult


class CredibilityLevel(str, Enum):
    """Legacy user-facing projection retained for existing clients."""

    RELIABLE = "reliable"
    CAUTION = "caution"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CredibilityAssessment:
    """An auditable result-use decision with per-quantity evidence."""

    level: CredibilityLevel
    reason_codes: tuple[str, ...]
    coefficients_usable: bool
    scientific_evidence: ScientificEvidence

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level.value,
            "reason_codes": list(self.reason_codes),
            "coefficients_usable": self.coefficients_usable,
            "scientific_evidence": self.scientific_evidence.to_dict(),
        }


def assess_credibility(
    convergence: ConvergenceResult,
    mesh_quality: Mapping[str, object] | None,
    *,
    validation_level: ValidationLevel | None = None,
    execution_status: ExecutionStatus = ExecutionStatus.COMPLETED,
) -> CredibilityAssessment:
    """Map numerical, mesh and validation evidence to explicit use permissions."""

    status = getattr(convergence, "status", None)
    if not isinstance(status, ConvergenceStatus):
        status = ConvergenceStatus.NOT_EVALUATED
    mesh_reasons = _mesh_failure_reasons(mesh_quality)
    coefficient_values = {
        "CL": getattr(convergence, "final_cl", None),
        "CD": getattr(convergence, "final_cd", None),
    }
    all_coefficients_finite = all(_finite(value) for value in coefficient_values.values())
    near_wall = _near_wall(mesh_quality)
    y_plus = _y_plus_evidence(near_wall, validation_level)
    near_wall_validated = (
        near_wall.get("drag_fidelity") == "validated_near_wall_layers"
        and near_wall.get("present") is True
    )
    y_plus_verified = y_plus.evidence_status is EvidenceStatus.VERIFIED
    validation_sufficient = (
        validation_level is not None
        and validation_level.rank >= ValidationLevel.L3.rank
    )

    reasons = _reason_codes(
        status=status,
        convergence=convergence,
        all_coefficients_finite=all_coefficients_finite,
        mesh_quality=mesh_quality,
        mesh_reasons=mesh_reasons,
        near_wall_validated=near_wall_validated,
        y_plus_status=y_plus.evidence_status,
        validation_sufficient=validation_sufficient,
    )
    diagnostic, trend = _base_permissions(status)
    if mesh_reasons:
        diagnostic = trend = False
    engineering = (
        status is ConvergenceStatus.CONVERGED
        and all_coefficients_finite
        and not mesh_reasons
        and near_wall_validated
        and y_plus_verified
        and validation_sufficient
    )

    quantities: dict[str, QuantityEvidence] = {}
    for name, raw_value in coefficient_values.items():
        finite = _finite(raw_value)
        quantities[name] = QuantityEvidence(
            quantity_name=name,
            value=float(raw_value) if finite else None,
            unit="1",
            source="SU2 history.csv final finite coefficient",
            calculation_method="final recorded force coefficient",
            evidence_status=(
                EvidenceStatus.COMPUTED if finite else EvidenceStatus.MISSING
            ),
            convergence_status=status,
            validation_level=validation_level,
            user_overridden=False,
            usable_for_diagnostic=finite and diagnostic,
            usable_for_trend=finite and trend,
            usable_for_engineering=finite and engineering,
            blocking_reasons=(() if finite and engineering else reasons),
            warnings=(),
        )
    quantities["y_plus"] = y_plus

    coefficients_usable = all(
        quantities[name].usable_for_engineering for name in ("CL", "CD")
    )
    scientific_use = _scientific_use(
        quantities,
        all_coefficients_finite=all_coefficients_finite,
        validation_level=validation_level,
    )
    evidence = ScientificEvidence(
        execution_status=execution_status,
        convergence_status=status,
        scientific_use_level=scientific_use,
        validation_level=validation_level,
        quantities=quantities,
        blocking_reasons=reasons,
        warnings=(),
    )
    level = (
        CredibilityLevel.RELIABLE
        if coefficients_usable
        else (
            CredibilityLevel.INVALID
            if scientific_use is ScientificUseLevel.INVALID
            else CredibilityLevel.CAUTION
        )
    )
    return CredibilityAssessment(level, reasons, coefficients_usable, evidence)


def _reason_codes(
    *,
    status: ConvergenceStatus,
    convergence: object,
    all_coefficients_finite: bool,
    mesh_quality: Mapping[str, object] | None,
    mesh_reasons: tuple[str, ...],
    near_wall_validated: bool,
    y_plus_status: EvidenceStatus,
    validation_sufficient: bool,
) -> tuple[str, ...]:
    if not all_coefficients_finite:
        return ("COEFFICIENTS_NONFINITE_OR_MISSING",)
    if status in {ConvergenceStatus.DIVERGED, ConvergenceStatus.INVALID}:
        return (f"CONVERGENCE_{status.value.upper()}",)
    if status is ConvergenceStatus.NOT_EVALUATED:
        return ("CONVERGENCE_NOT_FINAL",)
    if mesh_reasons:
        return mesh_reasons
    reasons: list[str] = []
    if status is ConvergenceStatus.STAGNATED:
        reasons.append("CONVERGENCE_STAGNATED")
    elif status is ConvergenceStatus.OSCILLATING:
        reasons.append("CONVERGENCE_OSCILLATING")
    elif status is ConvergenceStatus.INCOMPLETE:
        reason = getattr(convergence, "reason_code", "")
        reasons.append(
            reason
            if str(reason).startswith("SOLVER_")
            else "ITERATION_LIMIT_REACHED"
        )
    elif status is ConvergenceStatus.LIKELY_CONVERGED:
        reasons.append("CONVERGENCE_LIKELY_ONLY")
    if mesh_quality is None:
        reasons.append("MESH_EVIDENCE_MISSING")
    if not near_wall_validated:
        reasons.append("MESH_PREVIEW_ONLY")
    if y_plus_status is not EvidenceStatus.VERIFIED:
        reasons.append(_y_plus_blocking_reason(y_plus_status))
    if not validation_sufficient:
        reasons.append("VALIDATION_EVIDENCE_BELOW_L3")
    return tuple(reasons) or ("CONVERGED_WITH_VALIDATED_MESH",)


def _base_permissions(status: ConvergenceStatus) -> tuple[bool, bool]:
    if status in {ConvergenceStatus.CONVERGED, ConvergenceStatus.LIKELY_CONVERGED}:
        return True, True
    if status in {
        ConvergenceStatus.STAGNATED,
        ConvergenceStatus.OSCILLATING,
        ConvergenceStatus.INCOMPLETE,
    }:
        return True, False
    return False, False


def _y_plus_blocking_reason(status: EvidenceStatus) -> str:
    if status in {
        EvidenceStatus.ESTIMATED,
        EvidenceStatus.COMPUTED,
        EvidenceStatus.MEASURED,
    }:
        return "Y_PLUS_EVIDENCE_NOT_VERIFIED"
    return "Y_PLUS_EVIDENCE_MISSING"


def _scientific_use(
    quantities: Mapping[str, QuantityEvidence],
    *,
    all_coefficients_finite: bool,
    validation_level: ValidationLevel | None,
) -> ScientificUseLevel:
    core = [quantities[name] for name in ("CL", "CD")]
    if not all_coefficients_finite:
        return ScientificUseLevel.INVALID
    if all(item.usable_for_engineering for item in core):
        if (
            validation_level is not None
            and validation_level.rank >= ValidationLevel.L4.rank
        ):
            return ScientificUseLevel.EXTERNALLY_VALIDATED
        return ScientificUseLevel.ENGINEERING_COMPARISON
    if all(item.usable_for_trend for item in core):
        return ScientificUseLevel.TREND_ONLY
    if all(item.usable_for_diagnostic for item in core):
        return ScientificUseLevel.DIAGNOSTIC_ONLY
    return ScientificUseLevel.INVALID


def _y_plus_evidence(
    near_wall: Mapping[str, object],
    validation_level: ValidationLevel | None,
) -> QuantityEvidence:
    raw = near_wall.get("y_plus")
    raw = raw if isinstance(raw, Mapping) else {}
    value = raw.get("value")
    finite = _finite(value)
    try:
        status = EvidenceStatus(str(raw.get("status", "missing")))
    except ValueError:
        status = EvidenceStatus.INVALID
    if status not in {
        EvidenceStatus.ESTIMATED,
        EvidenceStatus.COMPUTED,
        EvidenceStatus.MEASURED,
        EvidenceStatus.VERIFIED,
    } or not finite:
        status = EvidenceStatus.MISSING if not raw else EvidenceStatus.INVALID
        value = None
    source = str(raw.get("source", "near-wall result unavailable"))
    return QuantityEvidence(
        quantity_name="y_plus",
        value=float(value) if value is not None else None,
        unit="1",
        source=source or "near-wall result unavailable",
        calculation_method="wall-field evidence supplied by the meshing/solver pipeline",
        evidence_status=status,
        convergence_status=ConvergenceStatus.NOT_EVALUATED,
        validation_level=validation_level,
        user_overridden=False,
        usable_for_diagnostic=value is not None,
        usable_for_trend=False,
        usable_for_engineering=False,
        blocking_reasons=(
            ()
            if status is EvidenceStatus.VERIFIED
            else (_y_plus_blocking_reason(status),)
        ),
        warnings=(),
    )


def _near_wall(mesh_quality: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(mesh_quality, Mapping):
        return {}
    value = mesh_quality.get("near_wall")
    return value if isinstance(value, Mapping) else {}


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _mesh_failure_reasons(
    mesh_quality: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if mesh_quality is None:
        return ()
    reasons: list[str] = []
    if int(mesh_quality.get("negative_quality_count", 0)) > 0:
        reasons.append("MESH_NEGATIVE_ELEMENTS")
    if int(mesh_quality.get("non_manifold_face_count", 0)) > 0:
        reasons.append("MESH_NON_MANIFOLD")
    groups = mesh_quality.get("physical_group_presence")
    if isinstance(groups, Mapping) and not all(bool(value) for value in groups.values()):
        reasons.append("MESH_PHYSICAL_GROUP_MISSING")
    near_wall = mesh_quality.get("near_wall")
    if (
        isinstance(near_wall, Mapping)
        and near_wall.get("required")
        and not near_wall.get("present")
    ):
        reasons.append("MESH_NEAR_WALL_LAYER_MISSING")
    return tuple(reasons)
