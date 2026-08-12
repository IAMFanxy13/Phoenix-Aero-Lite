"""Immutable, unit-bearing Phoenix Aero Lite result models."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math


@dataclass(frozen=True, slots=True)
class DerivedQuantity:
    """A finite scalar with an explicit unit and provenance expression."""

    value: float
    unit: str
    source: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, (int, float))
            or isinstance(self.value, bool)
            or not math.isfinite(self.value)
            or not isinstance(self.unit, str)
            or not self.unit
            or not isinstance(self.source, str)
            or not self.source
        ):
            raise ValueError("RESULT_QUANTITY_INVALID")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation."""

        return {
            "value": float(self.value),
            "unit": self.unit,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class AerodynamicSummary:
    """Auditable loads; invalid CFD states intentionally omit load claims."""

    valid: bool
    reason_code: str
    cl: DerivedQuantity | None
    cd: DerivedQuantity | None
    body_to_wind_drag_coefficient: DerivedQuantity | None
    body_to_wind_lift_coefficient: DerivedQuantity | None
    dynamic_pressure: DerivedQuantity
    lift: DerivedQuantity | None
    drag: DerivedQuantity | None
    weight: DerivedQuantity
    lift_margin: DerivedQuantity | None
    lift_to_weight_ratio: DerivedQuantity | None
    meets_weight_requirement: bool | None

    def to_dict(self) -> dict[str, object]:
        """Return a strict JSON-safe dictionary."""

        def quantity(value: DerivedQuantity | None) -> object:
            return value.to_dict() if value is not None else None

        return {
            "valid": self.valid,
            "reason_code": self.reason_code,
            "cl": quantity(self.cl),
            "cd": quantity(self.cd),
            "body_to_wind_drag_coefficient": quantity(
                self.body_to_wind_drag_coefficient
            ),
            "body_to_wind_lift_coefficient": quantity(
                self.body_to_wind_lift_coefficient
            ),
            "dynamic_pressure": quantity(self.dynamic_pressure),
            "lift": quantity(self.lift),
            "drag": quantity(self.drag),
            "weight": quantity(self.weight),
            "lift_margin": quantity(self.lift_margin),
            "lift_to_weight_ratio": quantity(self.lift_to_weight_ratio),
            "meets_weight_requirement": self.meets_weight_requirement,
        }

    def to_json(self) -> str:
        """Serialize without allowing NaN or Infinity."""

        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
