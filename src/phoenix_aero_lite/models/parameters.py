"""Immutable SI-domain input parameters for Phoenix Aero Lite."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .errors import ParameterValidationError, ValidationIssue, issue_for


class MeshMode(str, Enum):
    """Supported first-version mesh fidelity levels."""

    PREVIEW = "preview"
    STANDARD = "standard"
    FINE = "fine"


def _finite_positive(value: object, positive_code: str) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return (issue_for("PARAMETERS_FIELD_TYPE_INVALID"),)
    if not math.isfinite(value):
        return (issue_for("PARAMETER_VALUE_MUST_BE_FINITE"),)
    if value <= 0:
        return (issue_for(positive_code),)
    return ()


def _finite_angle(value: object) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return (issue_for("PARAMETERS_FIELD_TYPE_INVALID"),)
    if not math.isfinite(value):
        return (issue_for("PARAMETER_VALUE_MUST_BE_FINITE"),)
    if not -45.0 <= value <= 45.0:
        return (issue_for("ANGLE_OF_ATTACK_OUT_OF_RANGE"),)
    return ()


@dataclass(frozen=True, slots=True)
class FlowParameters:
    """Freestream state in SI units and angle of attack in degrees."""

    velocity_m_s: float
    density_kg_m3: float
    dynamic_viscosity_pa_s: float
    angle_of_attack_deg: float

    def validate(self) -> tuple[ValidationIssue, ...]:
        return (
            _finite_positive(self.velocity_m_s, "FLOW_VELOCITY_MUST_BE_POSITIVE")
            + _finite_positive(self.density_kg_m3, "FLOW_DENSITY_MUST_BE_POSITIVE")
            + _finite_positive(self.dynamic_viscosity_pa_s, "FLOW_VISCOSITY_MUST_BE_POSITIVE")
            + _finite_angle(self.angle_of_attack_deg)
        )


@dataclass(frozen=True, slots=True)
class ReferenceParameters:
    """User-provided aerodynamic reference values in SI units.

    They are intentionally not inferred from the geometry.
    """

    s_ref_m2: float
    c_ref_m: float

    def validate(self) -> tuple[ValidationIssue, ...]:
        return _finite_positive(self.s_ref_m2, "REFERENCE_AREA_MUST_BE_POSITIVE") + _finite_positive(
            self.c_ref_m, "REFERENCE_CHORD_MUST_BE_POSITIVE"
        )


@dataclass(frozen=True, slots=True)
class AircraftParameters:
    """Aircraft mass in kilograms."""

    mass_kg: float

    def validate(self) -> tuple[ValidationIssue, ...]:
        return _finite_positive(self.mass_kg, "AIRCRAFT_MASS_MUST_BE_POSITIVE")


@dataclass(frozen=True, slots=True)
class MeshParameters:
    """Meshing inputs, with a target cell size expressed in metres."""

    mode: MeshMode
    target_cell_size_m: float

    def validate(self) -> tuple[ValidationIssue, ...]:
        mode_issues = () if isinstance(self.mode, MeshMode) else (issue_for("MESH_MODE_INVALID"),)
        return mode_issues + _finite_positive(
            self.target_cell_size_m, "MESH_TARGET_CELL_SIZE_MUST_BE_POSITIVE"
        )


@dataclass(frozen=True, slots=True)
class SolverParameters:
    """Explicit solver run limits independent of mesh and flow inputs."""

    max_iterations: int

    def validate(self) -> tuple[ValidationIssue, ...]:
        if not isinstance(self.max_iterations, int) or isinstance(self.max_iterations, bool):
            return (issue_for("PARAMETERS_FIELD_TYPE_INVALID"),)
        if self.max_iterations <= 0:
            return (issue_for("SOLVER_MAX_ITERATIONS_MUST_BE_POSITIVE"),)
        return ()


@dataclass(frozen=True, slots=True)
class OutputParameters:
    """Case output location; creation remains the workflow's responsibility."""

    output_directory: Path

    def validate(self) -> tuple[ValidationIssue, ...]:
        if not isinstance(self.output_directory, Path):
            return (issue_for("PARAMETERS_FIELD_TYPE_INVALID"),)
        if not str(self.output_directory):
            return (issue_for("OUTPUT_DIRECTORY_MUST_BE_PROVIDED"),)
        return ()


@dataclass(frozen=True, slots=True)
class CaseParameters:
    """Composition root for the explicit inputs required to create one case."""

    flow: FlowParameters
    reference: ReferenceParameters
    aircraft: AircraftParameters
    mesh: MeshParameters
    solver: SolverParameters
    output: OutputParameters

    def validate(self) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        for value in (
            self.flow,
            self.reference,
            self.aircraft,
            self.mesh,
            self.solver,
            self.output,
        ):
            if not hasattr(value, "validate"):
                issues.append(issue_for("PARAMETERS_FIELD_TYPE_INVALID"))
            else:
                issues.extend(value.validate())
        return tuple(issues)

    def to_dict(self) -> dict[str, object]:
        _raise_if_invalid(self.validate())
        return {
            "flow": {
                "velocity_m_s": self.flow.velocity_m_s,
                "density_kg_m3": self.flow.density_kg_m3,
                "dynamic_viscosity_pa_s": self.flow.dynamic_viscosity_pa_s,
                "angle_of_attack_deg": self.flow.angle_of_attack_deg,
            },
            "reference": {"s_ref_m2": self.reference.s_ref_m2, "c_ref_m": self.reference.c_ref_m},
            "aircraft": {"mass_kg": self.aircraft.mass_kg},
            "mesh": {"mode": self.mesh.mode.value, "target_cell_size_m": self.mesh.target_cell_size_m},
            "solver": {"max_iterations": self.solver.max_iterations},
            "output": {"output_directory": str(self.output.output_directory)},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "CaseParameters":
        try:
            data = json.loads(payload, parse_constant=_reject_non_finite_json)
        except _NonFiniteJsonNumber:
            raise ParameterValidationError((issue_for("PARAMETERS_JSON_NON_FINITE_NUMBER"),)) from None
        except (TypeError, json.JSONDecodeError):
            raise ParameterValidationError((issue_for("PARAMETERS_JSON_INVALID"),)) from None
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseParameters":
        _require_fields(data, {"flow", "reference", "aircraft", "mesh", "solver", "output"})
        flow_data = _nested_fields(
            data["flow"],
            {"velocity_m_s", "density_kg_m3", "dynamic_viscosity_pa_s", "angle_of_attack_deg"},
        )
        reference_data = _nested_fields(data["reference"], {"s_ref_m2", "c_ref_m"})
        aircraft_data = _nested_fields(data["aircraft"], {"mass_kg"})
        mesh_data = _nested_fields(data["mesh"], {"mode", "target_cell_size_m"})
        solver_data = _nested_fields(data["solver"], {"max_iterations"})
        output_data = _nested_fields(data["output"], {"output_directory"})

        try:
            mode = MeshMode(mesh_data["mode"])
        except (TypeError, ValueError):
            raise ParameterValidationError((issue_for("MESH_MODE_INVALID"),)) from None

        output_directory = output_data["output_directory"]
        if not isinstance(output_directory, str):
            raise ParameterValidationError((issue_for("PARAMETERS_FIELD_TYPE_INVALID"),))
        if not output_directory:
            raise ParameterValidationError((issue_for("OUTPUT_DIRECTORY_MUST_BE_PROVIDED"),))
        result = cls(
            flow=FlowParameters(**flow_data),
            reference=ReferenceParameters(**reference_data),
            aircraft=AircraftParameters(**aircraft_data),
            mesh=MeshParameters(mode=mode, target_cell_size_m=mesh_data["target_cell_size_m"]),
            solver=SolverParameters(**solver_data),
            output=OutputParameters(output_directory=Path(output_directory)),
        )
        _raise_if_invalid(result.validate())
        return result


class _NonFiniteJsonNumber(ValueError):
    pass


def _reject_non_finite_json(_constant: str) -> None:
    raise _NonFiniteJsonNumber


def _raise_if_invalid(issues: tuple[ValidationIssue, ...]) -> None:
    if issues:
        raise ParameterValidationError(issues)


def _require_fields(data: object, expected: set[str]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ParameterValidationError((issue_for("PARAMETERS_FIELD_TYPE_INVALID"),))
    unknown = set(data) - expected
    if unknown:
        raise ParameterValidationError((issue_for("PARAMETERS_UNKNOWN_FIELD"),))
    if set(data) != expected:
        raise ParameterValidationError((issue_for("PARAMETERS_REQUIRED_FIELD_MISSING"),))
    return data


def _nested_fields(data: object, expected: set[str]) -> Mapping[str, Any]:
    return _require_fields(data, expected)
