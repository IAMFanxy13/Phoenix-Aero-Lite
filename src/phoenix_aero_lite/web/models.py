"""Typed web inputs mapped onto the existing core parameter model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True, slots=True)
class JobRequest:
    velocity_m_s: float
    angle_of_attack_deg: float
    s_ref_m2: float
    c_ref_m: float
    mass_kg: float
    density_kg_m3: float
    dynamic_viscosity_pa_s: float
    mesh_mode: MeshMode
    target_cell_size_m: float
    max_iterations: int

    def to_case_parameters(self, output_directory: Path) -> CaseParameters:
        parameters = CaseParameters(
            flow=FlowParameters(
                self.velocity_m_s,
                self.density_kg_m3,
                self.dynamic_viscosity_pa_s,
                self.angle_of_attack_deg,
            ),
            reference=ReferenceParameters(self.s_ref_m2, self.c_ref_m),
            aircraft=AircraftParameters(self.mass_kg),
            mesh=MeshParameters(self.mesh_mode, self.target_cell_size_m),
            solver=SolverParameters(self.max_iterations),
            output=OutputParameters(output_directory),
        )
        issues = parameters.validate()
        if issues:
            raise ValueError(issues[0].code)
        return parameters

    def to_dict(self) -> dict[str, object]:
        return {
            "velocity_m_s": self.velocity_m_s,
            "angle_of_attack_deg": self.angle_of_attack_deg,
            "s_ref_m2": self.s_ref_m2,
            "c_ref_m": self.c_ref_m,
            "mass_kg": self.mass_kg,
            "density_kg_m3": self.density_kg_m3,
            "dynamic_viscosity_pa_s": self.dynamic_viscosity_pa_s,
            "mesh_mode": self.mesh_mode.value,
            "target_cell_size_m": self.target_cell_size_m,
            "max_iterations": self.max_iterations,
        }


MAX_STEP_BYTES = 512 * 1024 * 1024
