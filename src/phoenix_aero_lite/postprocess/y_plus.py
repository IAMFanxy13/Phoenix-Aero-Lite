"""Auditable wall-Y+ statistics extracted from SU2 surface output.

SU2 exposes ``Y_PLUS`` in its primitive surface-output group.  This adapter
uses that solver-computed field; it never substitutes the target Y+ or the
meshing first-layer estimate for a solved value.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Mapping

import numpy as np
import pyvista as pv


_Y_PLUS_NAMES = {"yplus"}


@dataclass(frozen=True, slots=True)
class YPlusStatistics:
    """Strict-JSON-safe evidence for a solver-computed wall Y+ field."""

    evidence_status: str
    scalar_name: str | None
    sample_count: int
    missing_sample_count: int
    minimum: float | None
    maximum: float | None
    mean: float | None
    median: float | None
    p05: float | None
    p95: float | None
    out_of_target_area_fraction: float | None
    target_minimum: float
    target_maximum: float
    source: str
    calculation_method: str

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_status": self.evidence_status,
            "scalar_name": self.scalar_name,
            "sample_count": self.sample_count,
            "missing_sample_count": self.missing_sample_count,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "mean": self.mean,
            "median": self.median,
            "p05": self.p05,
            "p95": self.p95,
            "out_of_target_area_fraction": self.out_of_target_area_fraction,
            "target_range": [self.target_minimum, self.target_maximum],
            "source": self.source,
            "calculation_method": self.calculation_method,
        }


def analyze_y_plus_surface(
    surface_path: Path,
    *,
    target_range: tuple[float, float],
) -> YPlusStatistics:
    """Read SU2's wall field and return distribution plus area evidence.

    Point values are used for the distribution.  When every point value is
    finite, PyVista/VTK converts them to cell values and cell areas are used
    for the out-of-target area fraction.  Partial/non-finite fields retain
    valid distribution evidence but deliberately omit the area claim.
    """

    target_minimum, target_maximum = _validated_target_range(target_range)
    path = Path(surface_path)
    if not path.is_file():
        raise ValueError("Y_PLUS_SURFACE_FILE_MISSING")
    dataset = pv.read(path).extract_surface(algorithm="dataset_surface")
    scalar_name, association = _find_y_plus_array(dataset)
    if scalar_name is None:
        return _missing(target_minimum, target_maximum)

    raw = np.asarray(
        dataset.point_data[scalar_name]
        if association == "point"
        else dataset.cell_data[scalar_name],
        dtype=float,
    ).reshape(-1)
    finite_mask = np.isfinite(raw)
    finite_values = raw[finite_mask]
    missing_count = int(raw.size - finite_values.size)
    if finite_values.size == 0:
        return YPlusStatistics(
            evidence_status="invalid",
            scalar_name=scalar_name,
            sample_count=0,
            missing_sample_count=missing_count,
            minimum=None,
            maximum=None,
            mean=None,
            median=None,
            p05=None,
            p95=None,
            out_of_target_area_fraction=None,
            target_minimum=target_minimum,
            target_maximum=target_maximum,
            source=f"SU2 surface solution field {scalar_name}",
            calculation_method="SU2 computed wall Y+; field contains no finite samples",
        )

    area_fraction = None
    if missing_count == 0:
        area_fraction = _out_of_target_area_fraction(
            dataset,
            scalar_name=scalar_name,
            association=association,
            target_minimum=target_minimum,
            target_maximum=target_maximum,
        )
    return YPlusStatistics(
        evidence_status="computed",
        scalar_name=scalar_name,
        sample_count=int(finite_values.size),
        missing_sample_count=missing_count,
        minimum=float(np.min(finite_values)),
        maximum=float(np.max(finite_values)),
        mean=float(np.mean(finite_values)),
        median=float(np.median(finite_values)),
        p05=float(np.percentile(finite_values, 5.0)),
        p95=float(np.percentile(finite_values, 95.0)),
        out_of_target_area_fraction=area_fraction,
        target_minimum=target_minimum,
        target_maximum=target_maximum,
        source=f"SU2 surface solution field {scalar_name}",
        calculation_method=(
            "SU2 computed wall Y+ distribution; cell-area fraction uses "
            "VTK point-to-cell averaging when the source is point-associated"
        ),
    )


def merge_y_plus_evidence(
    mesh_quality: Mapping[str, object] | None,
    statistics: YPlusStatistics,
) -> dict[str, object]:
    """Return a copied mesh record augmented with solved Y+ evidence."""

    merged: dict[str, object] = dict(mesh_quality or {})
    raw_near_wall = merged.get("near_wall")
    near_wall = dict(raw_near_wall) if isinstance(raw_near_wall, Mapping) else {}
    payload = statistics.to_dict()
    near_wall["y_plus"] = {
        "value": statistics.mean,
        "status": statistics.evidence_status,
        "source": statistics.source,
        "calculation_method": statistics.calculation_method,
        "target_range": payload["target_range"],
        "distribution": {
            "minimum": statistics.minimum,
            "maximum": statistics.maximum,
            "mean": statistics.mean,
            "median": statistics.median,
            "p05": statistics.p05,
            "p95": statistics.p95,
            "out_of_target_area_fraction": statistics.out_of_target_area_fraction,
            "sample_count": statistics.sample_count,
            "missing_sample_count": statistics.missing_sample_count,
        },
    }
    merged["near_wall"] = near_wall
    return merged


def _validated_target_range(value: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError("Y_PLUS_TARGET_RANGE_INVALID")
    lower, upper = value
    if (
        not isinstance(lower, (int, float))
        or isinstance(lower, bool)
        or not isinstance(upper, (int, float))
        or isinstance(upper, bool)
        or not math.isfinite(lower)
        or not math.isfinite(upper)
        or lower < 0.0
        or lower >= upper
    ):
        raise ValueError("Y_PLUS_TARGET_RANGE_INVALID")
    return float(lower), float(upper)


def _find_y_plus_array(dataset: pv.DataSet) -> tuple[str | None, str | None]:
    for association, arrays in (
        ("point", dataset.point_data),
        ("cell", dataset.cell_data),
    ):
        for name in arrays.keys():
            normalized = "".join(character for character in name.lower() if character.isalnum())
            if normalized in _Y_PLUS_NAMES:
                return str(name), association
    return None, None


def _out_of_target_area_fraction(
    dataset: pv.DataSet,
    *,
    scalar_name: str,
    association: str,
    target_minimum: float,
    target_maximum: float,
) -> float | None:
    cell_dataset = (
        dataset.point_data_to_cell_data(pass_point_data=True)
        if association == "point"
        else dataset
    )
    values = np.asarray(cell_dataset.cell_data[scalar_name], dtype=float).reshape(-1)
    areas = np.asarray(
        cell_dataset.compute_cell_sizes(
            length=False, area=True, volume=False
        ).cell_data["Area"],
        dtype=float,
    ).reshape(-1)
    valid = np.isfinite(values) & np.isfinite(areas) & (areas > 0.0)
    total_area = float(np.sum(areas[valid]))
    if not np.any(valid) or total_area <= 0.0:
        return None
    outside = (values < target_minimum) | (values > target_maximum)
    return float(np.sum(areas[valid & outside]) / total_area)


def _missing(target_minimum: float, target_maximum: float) -> YPlusStatistics:
    return YPlusStatistics(
        evidence_status="missing",
        scalar_name=None,
        sample_count=0,
        missing_sample_count=0,
        minimum=None,
        maximum=None,
        mean=None,
        median=None,
        p05=None,
        p95=None,
        out_of_target_area_fraction=None,
        target_minimum=target_minimum,
        target_maximum=target_maximum,
        source="SU2 surface solution does not contain a Y_PLUS field",
        calculation_method="no solved wall Y+ evidence available",
    )
