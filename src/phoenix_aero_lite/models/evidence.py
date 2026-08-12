"""Canonical, conservative scientific evidence for one CFD case."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Mapping


class ExecutionStatus(str, Enum):
    """Workflow execution state; never expresses numerical convergence."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ConvergenceStatus(str, Enum):
    """Numerical state, independent from workflow execution and validation."""

    NOT_EVALUATED = "not_evaluated"
    CONVERGED = "converged"
    LIKELY_CONVERGED = "likely_converged"
    STAGNATED = "stagnated"
    OSCILLATING = "oscillating"
    DIVERGED = "diverged"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"

    # Source-compatible aliases for pre-schema-v2 callers.  Persisted values use
    # the canonical states above; these names can be removed after downstream
    # adapters have migrated.
    RUNNING = "not_evaluated"
    MAX_ITERATIONS = "incomplete"


class ScientificUseLevel(str, Enum):
    """Highest permitted scientific use of a case or result quantity."""

    INVALID = "invalid"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    TREND_ONLY = "trend_only"
    ENGINEERING_COMPARISON = "engineering_comparison"
    EXTERNALLY_VALIDATED = "externally_validated"


class ValidationLevel(str, Enum):
    """Evidence level attached to this case or quantity, never the software."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"

    @property
    def rank(self) -> int:
        return int(self.value[1:])


class EvidenceStatus(str, Enum):
    """How a value was obtained and whether any value exists."""

    UNKNOWN = "unknown"
    ESTIMATED = "estimated"
    COMPUTED = "computed"
    MEASURED = "measured"
    VERIFIED = "verified"
    MISSING = "missing"
    INVALID = "invalid"


_VALUE_STATUSES = {
    EvidenceStatus.ESTIMATED,
    EvidenceStatus.COMPUTED,
    EvidenceStatus.MEASURED,
    EvidenceStatus.VERIFIED,
}


@dataclass(frozen=True, slots=True)
class QuantityEvidence:
    """Traceable evidence and explicit permissions for one reported quantity."""

    quantity_name: str
    value: float | None
    unit: str
    source: str
    calculation_method: str
    evidence_status: EvidenceStatus
    convergence_status: ConvergenceStatus
    validation_level: ValidationLevel | None
    user_overridden: bool
    usable_for_diagnostic: bool
    usable_for_trend: bool
    usable_for_engineering: bool
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        value_is_finite = (
            isinstance(self.value, (int, float))
            and not isinstance(self.value, bool)
            and math.isfinite(self.value)
        )
        text_values = (
            self.quantity_name,
            self.unit,
            self.source,
            self.calculation_method,
        )
        flags = (
            self.user_overridden,
            self.usable_for_diagnostic,
            self.usable_for_trend,
            self.usable_for_engineering,
        )
        if (
            any(not isinstance(item, str) or not item for item in text_values)
            or not isinstance(self.evidence_status, EvidenceStatus)
            or not isinstance(self.convergence_status, ConvergenceStatus)
            or (
                self.validation_level is not None
                and not isinstance(self.validation_level, ValidationLevel)
            )
            or any(not isinstance(item, bool) for item in flags)
            or any(
                not isinstance(item, str) or not item
                for item in (*self.blocking_reasons, *self.warnings)
            )
            or (self.evidence_status in _VALUE_STATUSES and not value_is_finite)
            or (self.evidence_status not in _VALUE_STATUSES and self.value is not None)
            or (self.usable_for_engineering and not self.usable_for_trend)
            or (self.usable_for_trend and not self.usable_for_diagnostic)
            or (
                (self.value is None or self.evidence_status not in _VALUE_STATUSES)
                and any(
                    (
                        self.usable_for_diagnostic,
                        self.usable_for_trend,
                        self.usable_for_engineering,
                    )
                )
            )
        ):
            raise ValueError("QUANTITY_EVIDENCE_INVALID")
        if value_is_finite:
            object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "quantity_name": self.quantity_name,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "calculation_method": self.calculation_method,
            "evidence_status": self.evidence_status.value,
            "convergence_status": self.convergence_status.value,
            "validation_level": (
                self.validation_level.value if self.validation_level else None
            ),
            "user_overridden": self.user_overridden,
            "usable_for_diagnostic": self.usable_for_diagnostic,
            "usable_for_trend": self.usable_for_trend,
            "usable_for_engineering": self.usable_for_engineering,
            "blocking_reasons": list(self.blocking_reasons),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "QuantityEvidence":
        try:
            validation = payload.get("validation_level")
            return cls(
                quantity_name=str(payload["quantity_name"]),
                value=(
                    float(payload["value"])
                    if payload.get("value") is not None
                    else None
                ),
                unit=str(payload["unit"]),
                source=str(payload["source"]),
                calculation_method=str(payload["calculation_method"]),
                evidence_status=EvidenceStatus(str(payload["evidence_status"])),
                convergence_status=ConvergenceStatus(
                    str(payload["convergence_status"])
                ),
                validation_level=(
                    ValidationLevel(str(validation)) if validation is not None else None
                ),
                user_overridden=_strict_bool(payload["user_overridden"]),
                usable_for_diagnostic=_strict_bool(
                    payload["usable_for_diagnostic"]
                ),
                usable_for_trend=_strict_bool(payload["usable_for_trend"]),
                usable_for_engineering=_strict_bool(
                    payload["usable_for_engineering"]
                ),
                blocking_reasons=tuple(payload.get("blocking_reasons", ())),
                warnings=tuple(payload.get("warnings", ())),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("QUANTITY_EVIDENCE_INVALID") from None


@dataclass(frozen=True, slots=True)
class ScientificEvidence:
    """Case-level state and quantity evidence kept orthogonal by construction."""

    execution_status: ExecutionStatus = ExecutionStatus.DRAFT
    convergence_status: ConvergenceStatus = ConvergenceStatus.NOT_EVALUATED
    scientific_use_level: ScientificUseLevel = ScientificUseLevel.INVALID
    validation_level: ValidationLevel | None = None
    quantities: Mapping[str, QuantityEvidence] = field(default_factory=dict)
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            quantities = dict(self.quantities)
        except (TypeError, ValueError):
            raise ValueError("SCIENTIFIC_EVIDENCE_INVALID") from None
        if (
            not isinstance(self.execution_status, ExecutionStatus)
            or not isinstance(self.convergence_status, ConvergenceStatus)
            or not isinstance(self.scientific_use_level, ScientificUseLevel)
            or (
                self.validation_level is not None
                and not isinstance(self.validation_level, ValidationLevel)
            )
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(item, QuantityEvidence)
                or item.quantity_name != name
                for name, item in quantities.items()
            )
            or any(
                not isinstance(item, str) or not item
                for item in (*self.blocking_reasons, *self.warnings)
            )
            or (
                self.scientific_use_level
                is ScientificUseLevel.ENGINEERING_COMPARISON
                and (
                    self.validation_level is None
                    or self.validation_level.rank < ValidationLevel.L3.rank
                )
            )
            or (
                self.scientific_use_level
                is ScientificUseLevel.EXTERNALLY_VALIDATED
                and (
                    self.validation_level is None
                    or self.validation_level.rank < ValidationLevel.L4.rank
                )
            )
            or (
                self.scientific_use_level
                in {
                    ScientificUseLevel.ENGINEERING_COMPARISON,
                    ScientificUseLevel.EXTERNALLY_VALIDATED,
                }
                and any(
                    name not in quantities
                    or not quantities[name].usable_for_engineering
                    for name in ("CL", "CD")
                )
            )
        ):
            raise ValueError("SCIENTIFIC_EVIDENCE_INVALID")
        object.__setattr__(self, "quantities", MappingProxyType(quantities))
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_status": self.execution_status.value,
            "convergence_status": self.convergence_status.value,
            "scientific_use_level": self.scientific_use_level.value,
            "validation_level": (
                self.validation_level.value if self.validation_level else None
            ),
            "quantities": {
                name: quantity.to_dict()
                for name, quantity in sorted(self.quantities.items())
            },
            "blocking_reasons": list(self.blocking_reasons),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ScientificEvidence":
        if not payload:
            return cls()
        try:
            validation = payload.get("validation_level")
            raw_quantities = payload.get("quantities", {})
            if not isinstance(raw_quantities, Mapping):
                raise TypeError
            return cls(
                execution_status=ExecutionStatus(
                    str(payload.get("execution_status", "draft"))
                ),
                convergence_status=ConvergenceStatus(
                    str(payload.get("convergence_status", "not_evaluated"))
                ),
                scientific_use_level=ScientificUseLevel(
                    str(payload.get("scientific_use_level", "invalid"))
                ),
                validation_level=(
                    ValidationLevel(str(validation)) if validation is not None else None
                ),
                quantities={
                    str(name): QuantityEvidence.from_dict(item)
                    for name, item in raw_quantities.items()
                    if isinstance(item, Mapping)
                },
                blocking_reasons=tuple(payload.get("blocking_reasons", ())),
                warnings=tuple(payload.get("warnings", ())),
            )
        except (TypeError, ValueError):
            raise ValueError("SCIENTIFIC_EVIDENCE_INVALID") from None


def _strict_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("BOOLEAN_INVALID")
    return value
