from __future__ import annotations

import json

import pytest

from phoenix_aero_lite.solver.grid_study import (
    AerodynamicGridLevel,
    GridLevelResult,
    analyze_aerodynamic_grid_study,
    analyze_three_grid_quantity,
)


def _level(name: str, cells: int, value: float, *, status: str = "converged"):
    return GridLevelResult(
        level=name,
        cell_count=cells,
        value=value,
        convergence_status=status,
        common_setup_fingerprint="a" * 64,
        elapsed_seconds=float(cells) / 100.0,
    )


def test_computes_observed_order_richardson_and_gci_for_monotonic_family():
    result = analyze_three_grid_quantity(
        quantity_name="CL",
        unit="1",
        coarse=_level("coarse", 125, 1.04),
        medium=_level("medium", 1000, 1.01),
        fine=_level("fine", 8000, 1.0025),
    )

    assert result.classification == "monotonic"
    assert result.gci_computable is True
    assert result.blocking_reasons == ()
    assert result.refinement_ratio_medium_to_fine == pytest.approx(2.0)
    assert result.refinement_ratio_coarse_to_medium == pytest.approx(2.0)
    assert result.observed_order == pytest.approx(2.0)
    assert result.richardson_extrapolated_value == pytest.approx(1.0)
    assert result.gci_fine_fraction == pytest.approx(
        1.25 * abs((1.0025 - 1.01) / 1.0025) / 3.0
    )
    assert result.asymptotic_ratio == pytest.approx(1.0)
    assert result.asymptotic_range is True
    json.dumps(result.to_dict(), allow_nan=False)


def test_oscillatory_sequence_is_reported_without_fake_gci():
    result = analyze_three_grid_quantity(
        quantity_name="CD",
        unit="1",
        coarse=_level("coarse", 125, 0.10),
        medium=_level("medium", 1000, 0.12),
        fine=_level("fine", 8000, 0.11),
    )

    assert result.classification == "oscillatory"
    assert result.gci_computable is False
    assert result.gci_fine_fraction is None
    assert result.richardson_extrapolated_value is None
    assert result.blocking_reasons == ("GRID_SEQUENCE_OSCILLATORY",)


def test_all_three_solutions_must_be_iteratively_converged():
    result = analyze_three_grid_quantity(
        quantity_name="CL",
        unit="1",
        coarse=_level("coarse", 125, 1.04),
        medium=_level("medium", 1000, 1.01, status="stagnated"),
        fine=_level("fine", 8000, 1.0025),
    )

    assert result.classification == "blocked"
    assert result.gci_computable is False
    assert result.blocking_reasons == ("GRID_LEVEL_NOT_ITERATIVELY_CONVERGED",)


def test_common_setup_fingerprint_must_match():
    fine = _level("fine", 8000, 1.0025)
    fine = GridLevelResult(
        level=fine.level,
        cell_count=fine.cell_count,
        value=fine.value,
        convergence_status=fine.convergence_status,
        common_setup_fingerprint="b" * 64,
        elapsed_seconds=fine.elapsed_seconds,
    )
    result = analyze_three_grid_quantity(
        quantity_name="CL",
        unit="1",
        coarse=_level("coarse", 125, 1.04),
        medium=_level("medium", 1000, 1.01),
        fine=fine,
    )

    assert result.classification == "blocked"
    assert result.blocking_reasons == ("GRID_COMMON_SETUP_MISMATCH",)


def test_materially_inconsistent_effective_ratios_block_gci():
    result = analyze_three_grid_quantity(
        quantity_name="CL",
        unit="1",
        coarse=_level("coarse", 100, 1.04),
        medium=_level("medium", 800, 1.01),
        fine=_level("fine", 2700, 1.0025),
    )

    assert result.classification == "blocked"
    assert result.gci_computable is False
    assert result.blocking_reasons == ("GRID_REFINEMENT_RATIO_INCONSISTENT",)


@pytest.mark.parametrize(
    ("coarse_value", "medium_value", "fine_value", "reason"),
    [
        (1.0, 1.0, 1.0, "GRID_SEQUENCE_DEGENERATE"),
        (1.0, 1.0, 0.9, "GRID_SEQUENCE_DEGENERATE"),
    ],
)
def test_degenerate_sequence_is_not_promoted(
    coarse_value: float, medium_value: float, fine_value: float, reason: str
):
    result = analyze_three_grid_quantity(
        quantity_name="CL",
        unit="1",
        coarse=_level("coarse", 125, coarse_value),
        medium=_level("medium", 1000, medium_value),
        fine=_level("fine", 8000, fine_value),
    )

    assert result.gci_computable is False
    assert result.blocking_reasons == (reason,)


def test_aerodynamic_study_reports_cl_cd_and_lift_to_drag_with_costs():
    def aero(level: str, cells: int, cl: float, cd: float) -> AerodynamicGridLevel:
        return AerodynamicGridLevel(
            level=level,
            node_count=cells // 2,
            cell_count=cells,
            cl=cl,
            cd=cd,
            convergence_status="converged",
            common_setup_fingerprint="c" * 64,
            elapsed_seconds=float(cells),
        )

    result = analyze_aerodynamic_grid_study(
        coarse=aero("coarse", 125, 1.04, 0.104),
        medium=aero("medium", 1000, 1.01, 0.101),
        fine=aero("fine", 8000, 1.0025, 0.10025),
    )

    assert set(result) == {"CL", "CD", "L/D"}
    assert result["CL"].gci_computable is True
    assert result["CD"].gci_computable is True
    assert result["L/D"].gci_computable is False
    assert result["L/D"].blocking_reasons == ("GRID_SEQUENCE_DEGENERATE",)
    assert result["L/D"].levels[-1].value == pytest.approx(10.0)
    payload = result["CL"].to_dict()
    assert payload["levels"][0]["cell_count"] == 125
    assert payload["levels"][0]["node_count"] == 62


def test_two_dimensional_public_grid_family_uses_square_root_refinement_ratio():
    levels = [
        AerodynamicGridLevel("coarse", 225 * 65, 224 * 64, 0.0, 0.00846612, "converged", "a" * 64, 1.0, spatial_dimension=2),
        AerodynamicGridLevel("medium", 449 * 129, 448 * 128, 0.0, 0.00826384, "converged", "a" * 64, 2.0, spatial_dimension=2),
        AerodynamicGridLevel("fine", 897 * 257, 896 * 256, 0.0, 0.00820820, "converged", "a" * 64, 4.0, spatial_dimension=2),
    ]

    result = analyze_aerodynamic_grid_study(
        coarse=levels[0], medium=levels[1], fine=levels[2]
    )

    assert result["CD"].refinement_ratio_coarse_to_medium == pytest.approx(2.0)
    assert result["CD"].refinement_ratio_medium_to_fine == pytest.approx(2.0)
    assert result["CD"].gci_computable is True
