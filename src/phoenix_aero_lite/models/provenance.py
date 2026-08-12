"""Traceable automatic values and user overrides."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeAlias


ParameterValue: TypeAlias = float | str


class ParameterSource(str, Enum):
    MODEL_READ = "model_read"
    SOFTWARE_COMPUTED = "software_computed"
    USER_INPUT = "user_input"
    SOFTWARE_DEFAULT = "software_default"
    USER_OVERRIDE = "user_override"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ProvenancedValue:
    name: str
    unit: str
    detected_value: ParameterValue
    current_value: ParameterValue
    source: ParameterSource
    rationale: str
    confidence: Confidence
    confirmed: bool
    overridden: bool = False
    original_source: ParameterSource | None = None
    updated_at: str | None = None

    def with_user_value(
        self,
        value: ParameterValue,
        *,
        confirmed: bool,
        updated_at: str,
    ) -> "ProvenancedValue":
        return replace(
            self,
            current_value=value,
            source=ParameterSource.USER_OVERRIDE,
            confirmed=confirmed,
            overridden=value != self.detected_value,
            original_source=self.original_source or self.source,
            updated_at=updated_at,
        )

    def restore_detected(self, *, updated_at: str) -> "ProvenancedValue":
        """Restore the automatic candidate without erasing override history."""

        restored_source = self.original_source or self.source
        if restored_source is ParameterSource.USER_OVERRIDE:
            restored_source = ParameterSource.SOFTWARE_DEFAULT
        return replace(
            self,
            current_value=self.detected_value,
            source=restored_source,
            original_source=restored_source,
            confirmed=False,
            overridden=False,
            updated_at=updated_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "unit": self.unit,
            "detected_value": self.detected_value,
            "current_value": self.current_value,
            "source": self.source.value,
            "original_source": (
                self.original_source or self.source
            ).value,
            "rationale": self.rationale,
            "confidence": self.confidence.value,
            "confirmed": self.confirmed,
            "overridden": self.overridden,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProvenancedValue":
        original = payload.get("original_source")
        return cls(
            name=str(payload["name"]),
            unit=str(payload.get("unit", "")),
            detected_value=payload["detected_value"],
            current_value=payload["current_value"],
            source=ParameterSource(str(payload["source"])),
            original_source=(
                ParameterSource(str(original)) if original is not None else None
            ),
            rationale=str(payload.get("rationale", "")),
            confidence=Confidence(str(payload["confidence"])),
            confirmed=bool(payload.get("confirmed", False)),
            overridden=bool(payload.get("overridden", False)),
            updated_at=(
                str(payload["updated_at"])
                if payload.get("updated_at") is not None
                else None
            ),
        )
