from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyvista as pv
import pytest

from phoenix_aero_lite.postprocess.y_plus import (
    analyze_y_plus_surface,
    merge_y_plus_evidence,
)


def _surface(path: Path, *, array_name: str | None = "Y_Plus") -> Path:
    mesh = pv.PolyData(
        np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        ),
        np.array([3, 0, 1, 2, 3, 0, 2, 3]),
    )
    if array_name is not None:
        mesh.point_data[array_name] = np.array([0.5, 1.0, 2.0, 4.0])
    mesh.save(path)
    return path


def test_reads_real_su2_y_plus_field_and_reports_distribution_and_area(tmp_path: Path):
    result = analyze_y_plus_surface(
        _surface(tmp_path / "surface_flow.vtp"),
        target_range=(0.8, 1.5),
    )

    assert result.evidence_status == "computed"
    assert result.scalar_name == "Y_Plus"
    assert result.sample_count == 4
    assert result.missing_sample_count == 0
    assert result.minimum == pytest.approx(0.5)
    assert result.maximum == pytest.approx(4.0)
    assert result.mean == pytest.approx(1.875)
    assert result.median == pytest.approx(1.5)
    assert result.p05 == pytest.approx(0.575)
    assert result.p95 == pytest.approx(3.7)
    assert result.out_of_target_area_fraction == pytest.approx(0.5)
    assert result.source == "SU2 surface solution field Y_Plus"
    assert result.calculation_method.startswith("SU2 computed wall Y+")
    json.dumps(result.to_dict(), allow_nan=False)


def test_accepts_normalized_yplus_name_but_preserves_actual_field_name(tmp_path: Path):
    result = analyze_y_plus_surface(
        _surface(tmp_path / "alternate.vtp", array_name="y-plus"),
        target_range=(0.0, 10.0),
    )

    assert result.evidence_status == "computed"
    assert result.scalar_name == "y-plus"


def test_missing_y_plus_field_stays_missing_instead_of_inventing_a_value(tmp_path: Path):
    result = analyze_y_plus_surface(
        _surface(tmp_path / "missing.vtp", array_name=None),
        target_range=(0.8, 1.5),
    )

    assert result.evidence_status == "missing"
    assert result.scalar_name is None
    assert result.sample_count == 0
    assert result.mean is None
    assert result.out_of_target_area_fraction is None


@pytest.mark.parametrize("target_range", [(1.0, 1.0), (2.0, 1.0), (-1.0, 1.0)])
def test_rejects_invalid_target_range(tmp_path: Path, target_range: tuple[float, float]):
    with pytest.raises(ValueError, match="Y_PLUS_TARGET_RANGE_INVALID"):
        analyze_y_plus_surface(
            _surface(tmp_path / "invalid-range.vtp"),
            target_range=target_range,
        )


def test_nonfinite_samples_are_counted_and_never_serialized(tmp_path: Path):
    path = _surface(tmp_path / "partial.vtp")
    mesh = pv.read(path)
    mesh.point_data["Y_Plus"] = np.array([0.5, np.nan, 2.0, np.inf])
    mesh.save(path)

    result = analyze_y_plus_surface(path, target_range=(0.8, 1.5))

    assert result.evidence_status == "computed"
    assert result.sample_count == 2
    assert result.missing_sample_count == 2
    assert result.minimum == pytest.approx(0.5)
    assert result.maximum == pytest.approx(2.0)
    assert result.out_of_target_area_fraction is None
    json.dumps(result.to_dict(), allow_nan=False)


def test_merge_adds_solver_evidence_without_mutating_mesh_quality(tmp_path: Path):
    result = analyze_y_plus_surface(
        _surface(tmp_path / "surface.vtp"), target_range=(0.0, 1.0)
    )
    original = {"near_wall": {"present": True, "drag_fidelity": "validated_near_wall_layers"}}

    merged = merge_y_plus_evidence(original, result)

    assert "y_plus" not in original["near_wall"]
    assert merged["near_wall"]["y_plus"]["status"] == "computed"
    assert merged["near_wall"]["y_plus"]["value"] == pytest.approx(result.mean)
    assert merged["near_wall"]["y_plus"]["distribution"]["p95"] == pytest.approx(3.7)
    assert merged["near_wall"]["y_plus"]["target_range"] == [0.0, 1.0]
