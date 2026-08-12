"""Convert converged SU2 coefficients into traceable SI loads."""

from __future__ import annotations

import math

from phoenix_aero_lite.models.parameters import CaseParameters
from phoenix_aero_lite.models.results import (
    AerodynamicSummary,
    DerivedQuantity,
)
from phoenix_aero_lite.solver.convergence import (
    ConvergenceResult,
    ConvergenceStatus,
)
from phoenix_aero_lite.solver.su2_history import HistorySample


STANDARD_GRAVITY_M_S2 = 9.80665


class AeroSummaryError(ValueError):
    """Stable aerodynamic summary boundary failure."""


def body_to_wind_coefficients(
    force_x_coefficient: float,
    force_z_coefficient: float,
    angle_of_attack_deg: float,
) -> tuple[float, float]:
    """Rotate +x/+z body force coefficients into drag/lift axes.

    The body frame is +x forward and +z up.  Positive angle of attack rotates
    the freestream velocity toward +z, so:

    ``CD = CFx*cos(alpha) + CFz*sin(alpha)``
    ``CL = -CFx*sin(alpha) + CFz*cos(alpha)``
    """

    values = (
        force_x_coefficient,
        force_z_coefficient,
        angle_of_attack_deg,
    )
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        for value in values
    ):
        raise AeroSummaryError("AERO_COEFFICIENT_INVALID")
    angle = math.radians(angle_of_attack_deg)
    drag = force_x_coefficient * math.cos(angle) + force_z_coefficient * math.sin(
        angle
    )
    lift = -force_x_coefficient * math.sin(
        angle
    ) + force_z_coefficient * math.cos(angle)
    return drag, lift


def summarize_aerodynamics(
    parameters: CaseParameters,
    convergence: ConvergenceResult,
    final_sample: HistorySample,
) -> AerodynamicSummary:
    """Create load and lift-margin results only for converged finite CFD."""

    if not isinstance(parameters, CaseParameters) or parameters.validate():
        raise AeroSummaryError("AERO_INPUT_INVALID")
    if not isinstance(convergence, ConvergenceResult) or not isinstance(
        final_sample, HistorySample
    ):
        raise AeroSummaryError("AERO_RESULT_INVALID")

    density = float(parameters.flow.density_kg_m3)
    velocity = float(parameters.flow.velocity_m_s)
    area = float(parameters.reference.s_ref_m2)
    mass = float(parameters.aircraft.mass_kg)
    dynamic_pressure_value = 0.5 * density * velocity**2
    weight_value = mass * STANDARD_GRAVITY_M_S2
    dynamic_pressure = DerivedQuantity(
        dynamic_pressure_value,
        "Pa",
        "0.5 * density_kg_m3 * velocity_m_s^2",
    )
    weight = DerivedQuantity(
        weight_value,
        "N",
        "mass_kg * 9.80665_m_s2",
    )

    coefficient_values = (
        final_sample.cl,
        final_sample.cd,
        final_sample.force_x,
        final_sample.force_z,
    )
    if any(
        value is None
        or not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        for value in coefficient_values
    ):
        raise AeroSummaryError("AERO_COEFFICIENT_INVALID")
    assert final_sample.cl is not None
    assert final_sample.cd is not None
    assert final_sample.force_x is not None
    assert final_sample.force_z is not None
    rotated_drag, rotated_lift = body_to_wind_coefficients(
        final_sample.force_x,
        final_sample.force_z,
        parameters.flow.angle_of_attack_deg,
    )

    if convergence.status is not ConvergenceStatus.CONVERGED:
        return AerodynamicSummary(
            valid=False,
            reason_code="CFD_NOT_CONVERGED",
            cl=DerivedQuantity(
                final_sample.cl,
                "1",
                "unconverged SU2 history CL; diagnostic only",
            ),
            cd=DerivedQuantity(
                final_sample.cd,
                "1",
                "unconverged SU2 history CD; diagnostic only",
            ),
            body_to_wind_drag_coefficient=DerivedQuantity(
                rotated_drag,
                "1",
                "unconverged CFx*cos(alpha) + CFz*sin(alpha); diagnostic only",
            ),
            body_to_wind_lift_coefficient=DerivedQuantity(
                rotated_lift,
                "1",
                "unconverged -CFx*sin(alpha) + CFz*cos(alpha); diagnostic only",
            ),
            dynamic_pressure=dynamic_pressure,
            lift=None,
            drag=None,
            weight=weight,
            lift_margin=None,
            lift_to_weight_ratio=None,
            meets_weight_requirement=None,
        )

    if (
        convergence.final_cl is None
        or convergence.final_cd is None
        or not math.isclose(
            convergence.final_cl,
            final_sample.cl,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            convergence.final_cd,
            final_sample.cd,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise AeroSummaryError("AERO_RESULT_MISMATCH")

    lift_value = final_sample.cl * dynamic_pressure_value * area
    drag_value = final_sample.cd * dynamic_pressure_value * area
    margin_value = lift_value - weight_value
    ratio_value = lift_value / weight_value
    return AerodynamicSummary(
        valid=True,
        reason_code="CONVERGED_LOADS_AVAILABLE",
        cl=DerivedQuantity(final_sample.cl, "1", "SU2 history CL"),
        cd=DerivedQuantity(final_sample.cd, "1", "SU2 history CD"),
        body_to_wind_drag_coefficient=DerivedQuantity(
            rotated_drag,
            "1",
            "CFx*cos(alpha) + CFz*sin(alpha)",
        ),
        body_to_wind_lift_coefficient=DerivedQuantity(
            rotated_lift,
            "1",
            "-CFx*sin(alpha) + CFz*cos(alpha)",
        ),
        dynamic_pressure=dynamic_pressure,
        lift=DerivedQuantity(
            lift_value,
            "N",
            "SU2 CL * dynamic_pressure_Pa * S_ref_m2",
        ),
        drag=DerivedQuantity(
            drag_value,
            "N",
            "SU2 CD * dynamic_pressure_Pa * S_ref_m2",
        ),
        weight=weight,
        lift_margin=DerivedQuantity(
            margin_value,
            "N",
            "lift_N - weight_N",
        ),
        lift_to_weight_ratio=DerivedQuantity(
            ratio_value,
            "1",
            "lift_N / weight_N",
        ),
        meets_weight_requirement=margin_value >= 0.0,
    )
