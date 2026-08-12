"""Conservative three-grid Richardson/GCI analysis.

The implementation follows the NASA/NPARC presentation of Roache's method.
It deliberately withholds GCI when iterative convergence, common setup,
effective refinement, or monotonic spatial convergence cannot be established.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


_SAFETY_FACTOR_THREE_GRIDS = 1.25
_RATIO_RELATIVE_TOLERANCE = 0.05
_ASYMPTOTIC_RATIO_TOLERANCE = 0.10


@dataclass(frozen=True, slots=True)
class GridLevelResult:
    """One iteratively assessed solution in a common grid family."""

    level: str
    cell_count: int
    value: float
    convergence_status: str
    common_setup_fingerprint: str
    elapsed_seconds: float | None
    node_count: int | None = None

    def __post_init__(self) -> None:
        if (
            self.level not in {"coarse", "medium", "fine"}
            or not isinstance(self.cell_count, int)
            or isinstance(self.cell_count, bool)
            or self.cell_count <= 0
            or not _finite(self.value)
            or (self.elapsed_seconds is not None and (not _finite(self.elapsed_seconds) or self.elapsed_seconds < 0.0))
            or len(self.common_setup_fingerprint) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in self.common_setup_fingerprint)
            or (
                self.node_count is not None
                and (
                    not isinstance(self.node_count, int)
                    or isinstance(self.node_count, bool)
                    or self.node_count <= 0
                )
            )
        ):
            raise ValueError("GRID_LEVEL_RESULT_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "cell_count": self.cell_count,
            "node_count": self.node_count,
            "value": float(self.value),
            "convergence_status": self.convergence_status,
            "common_setup_fingerprint": self.common_setup_fingerprint,
            "elapsed_seconds": float(self.elapsed_seconds) if self.elapsed_seconds is not None else None,
        }


@dataclass(frozen=True, slots=True)
class AerodynamicGridLevel:
    """CL/CD result and execution cost for one member of a grid family."""

    level: str
    node_count: int
    cell_count: int
    cl: float
    cd: float
    convergence_status: str
    common_setup_fingerprint: str
    elapsed_seconds: float | None
    spatial_dimension: int = 3

    def __post_init__(self) -> None:
        if not _finite(self.cl) or not _finite(self.cd) or abs(self.cd) <= 1.0e-15:
            raise ValueError("GRID_AERODYNAMIC_RESULT_INVALID")
        if self.spatial_dimension not in {2, 3}:
            raise ValueError("GRID_SPATIAL_DIMENSION_INVALID")
        GridLevelResult(
            level=self.level,
            node_count=self.node_count,
            cell_count=self.cell_count,
            value=self.cl,
            convergence_status=self.convergence_status,
            common_setup_fingerprint=self.common_setup_fingerprint,
            elapsed_seconds=self.elapsed_seconds,
        )


@dataclass(frozen=True, slots=True)
class GridConvergenceResult:
    """A result that can represent either valid GCI or a precise block."""

    quantity_name: str
    unit: str
    levels: tuple[GridLevelResult, GridLevelResult, GridLevelResult]
    classification: str
    gci_computable: bool
    blocking_reasons: tuple[str, ...]
    refinement_ratio_coarse_to_medium: float
    refinement_ratio_medium_to_fine: float
    observed_order: float | None = None
    richardson_extrapolated_value: float | None = None
    gci_fine_fraction: float | None = None
    gci_medium_fraction: float | None = None
    asymptotic_ratio: float | None = None
    asymptotic_range: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "quantity_name": self.quantity_name,
            "unit": self.unit,
            "levels": [level.to_dict() for level in self.levels],
            "classification": self.classification,
            "gci_computable": self.gci_computable,
            "blocking_reasons": list(self.blocking_reasons),
            "effective_refinement_ratios": {
                "coarse_to_medium": self.refinement_ratio_coarse_to_medium,
                "medium_to_fine": self.refinement_ratio_medium_to_fine,
            },
            "observed_order": self.observed_order,
            "richardson_extrapolated_value": self.richardson_extrapolated_value,
            "gci_fine_fraction": self.gci_fine_fraction,
            "gci_medium_fraction": self.gci_medium_fraction,
            "asymptotic_ratio": self.asymptotic_ratio,
            "asymptotic_range": self.asymptotic_range,
            "method": "Roache three-grid GCI with safety factor 1.25",
        }


def analyze_three_grid_quantity(
    *,
    quantity_name: str,
    unit: str,
    coarse: GridLevelResult,
    medium: GridLevelResult,
    fine: GridLevelResult,
    spatial_dimension: int = 3,
) -> GridConvergenceResult:
    """Analyze an equally refined three-dimensional unstructured family."""

    if not quantity_name or not unit:
        raise ValueError("GRID_QUANTITY_INVALID")
    levels = (coarse, medium, fine)
    if tuple(level.level for level in levels) != ("coarse", "medium", "fine"):
        raise ValueError("GRID_LEVEL_ORDER_INVALID")
    if not coarse.cell_count < medium.cell_count < fine.cell_count:
        raise ValueError("GRID_CELL_COUNTS_NOT_REFINED")
    if spatial_dimension not in {2, 3}:
        raise ValueError("GRID_SPATIAL_DIMENSION_INVALID")
    r32 = (medium.cell_count / coarse.cell_count) ** (1.0 / spatial_dimension)
    r21 = (fine.cell_count / medium.cell_count) ** (1.0 / spatial_dimension)

    def blocked(reason: str, classification: str = "blocked") -> GridConvergenceResult:
        return GridConvergenceResult(
            quantity_name=quantity_name,
            unit=unit,
            levels=levels,
            classification=classification,
            gci_computable=False,
            blocking_reasons=(reason,),
            refinement_ratio_coarse_to_medium=r32,
            refinement_ratio_medium_to_fine=r21,
        )

    if any(level.convergence_status != "converged" for level in levels):
        return blocked("GRID_LEVEL_NOT_ITERATIVELY_CONVERGED")
    if len({level.common_setup_fingerprint for level in levels}) != 1:
        return blocked("GRID_COMMON_SETUP_MISMATCH")
    if min(r21, r32) <= 1.0:
        return blocked("GRID_REFINEMENT_RATIO_INVALID")
    if abs(r21 - r32) / max(r21, r32) > _RATIO_RELATIVE_TOLERANCE:
        return blocked("GRID_REFINEMENT_RATIO_INCONSISTENT")

    delta32 = coarse.value - medium.value
    delta21 = medium.value - fine.value
    tolerance = max(1.0e-15, max(abs(level.value) for level in levels) * 1.0e-14)
    if abs(delta32) <= tolerance or abs(delta21) <= tolerance:
        return blocked("GRID_SEQUENCE_DEGENERATE", "degenerate")
    if delta32 * delta21 < 0.0:
        return blocked("GRID_SEQUENCE_OSCILLATORY", "oscillatory")

    representative_ratio = math.sqrt(r21 * r32)
    observed_order = abs(
        math.log(abs(delta32 / delta21)) / math.log(representative_ratio)
    )
    denominator = representative_ratio**observed_order - 1.0
    if not math.isfinite(observed_order) or observed_order <= 0.0 or denominator <= 0.0:
        return blocked("GRID_OBSERVED_ORDER_INVALID")
    if abs(fine.value) <= tolerance or abs(medium.value) <= tolerance:
        return blocked("GRID_RELATIVE_ERROR_UNDEFINED")

    extrapolated = fine.value + (fine.value - medium.value) / denominator
    gci_fine = (
        _SAFETY_FACTOR_THREE_GRIDS
        * abs((fine.value - medium.value) / fine.value)
        / denominator
    )
    gci_medium = (
        _SAFETY_FACTOR_THREE_GRIDS
        * abs((medium.value - coarse.value) / medium.value)
        / denominator
    )
    asymptotic_ratio = abs(delta32) / (
        representative_ratio**observed_order * abs(delta21)
    )
    asymptotic_range = abs(asymptotic_ratio - 1.0) <= _ASYMPTOTIC_RATIO_TOLERANCE
    return GridConvergenceResult(
        quantity_name=quantity_name,
        unit=unit,
        levels=levels,
        classification="monotonic",
        gci_computable=True,
        blocking_reasons=(),
        refinement_ratio_coarse_to_medium=r32,
        refinement_ratio_medium_to_fine=r21,
        observed_order=observed_order,
        richardson_extrapolated_value=extrapolated,
        gci_fine_fraction=gci_fine,
        gci_medium_fraction=gci_medium,
        asymptotic_ratio=asymptotic_ratio,
        asymptotic_range=asymptotic_range,
    )


def analyze_aerodynamic_grid_study(
    *,
    coarse: AerodynamicGridLevel,
    medium: AerodynamicGridLevel,
    fine: AerodynamicGridLevel,
) -> dict[str, GridConvergenceResult]:
    """Apply the same scientific gates independently to CL, CD and L/D."""

    aerodynamic_levels = (coarse, medium, fine)
    if len({level.spatial_dimension for level in aerodynamic_levels}) != 1:
        raise ValueError("GRID_SPATIAL_DIMENSION_MISMATCH")

    def levels_for(attribute: str) -> tuple[GridLevelResult, ...]:
        converted: list[GridLevelResult] = []
        for level in aerodynamic_levels:
            value = (
                level.cl / level.cd
                if attribute == "lift_to_drag"
                else getattr(level, attribute)
            )
            converted.append(
                GridLevelResult(
                    level=level.level,
                    node_count=level.node_count,
                    cell_count=level.cell_count,
                    value=value,
                    convergence_status=level.convergence_status,
                    common_setup_fingerprint=level.common_setup_fingerprint,
                    elapsed_seconds=level.elapsed_seconds,
                )
            )
        return tuple(converted)

    result: dict[str, GridConvergenceResult] = {}
    for name, attribute in (("CL", "cl"), ("CD", "cd"), ("L/D", "lift_to_drag")):
        levels = levels_for(attribute)
        result[name] = analyze_three_grid_quantity(
            quantity_name=name,
            unit="1",
            coarse=levels[0],
            medium=levels[1],
            fine=levels[2],
            spatial_dimension=coarse.spatial_dimension,
        )
    return result


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )
