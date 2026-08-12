"""Unit contract for immutable geometry inspection and frame mapping."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import math

import pytest

from phoenix_aero_lite.models.geometry import (
    BoundingBox,
    GeometryInspection,
    ORIGINAL_TO_SU2_TRANSFORM,
)


def test_bounding_box_reports_dimensions_and_diagonal_in_metres():
    bounds = BoundingBox(
        minimum_m=(-1.0, 2.0, -3.0),
        maximum_m=(2.0, 6.0, 9.0),
    )

    assert bounds.dimensions_m == (3.0, 4.0, 12.0)
    assert bounds.diagonal_m == pytest.approx(13.0)


def test_geometry_results_are_immutable_and_keep_explicit_metre_metadata():
    bounds = BoundingBox(minimum_m=(0.0, 0.0, 0.0), maximum_m=(1.0, 2.0, 3.0))
    inspection = GeometryInspection(
        volume_count=1,
        surface_count=6,
        bounding_box=bounds,
        unit="m",
        scale_note="OpenCASCADE target unit forced to metres (M).",
    )

    assert inspection.bounding_box_min_m == (0.0, 0.0, 0.0)
    assert inspection.bounding_box_max_m == (1.0, 2.0, 3.0)
    assert inspection.dimensions_m == (1.0, 2.0, 3.0)
    assert inspection.diagonal_m == pytest.approx(math.sqrt(14.0))
    with pytest.raises(FrozenInstanceError):
        inspection.volume_count = 2
    with pytest.raises(FrozenInstanceError):
        bounds.minimum_m = (-1.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("original", "expected_su2"),
    [
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ((0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)),
        ((2.0, -3.0, 5.0), (-5.0, 2.0, -3.0)),
    ],
)
def test_approved_original_to_su2_basis_mapping(original, expected_su2):
    assert ORIGINAL_TO_SU2_TRANSFORM.apply(original) == expected_su2


def test_coordinate_transform_record_is_stable_manifest_data_without_aoa_rotation():
    record = ORIGINAL_TO_SU2_TRANSFORM.to_manifest()

    assert record == {
        "name": "original_to_su2",
        "source_frame": "original_cad",
        "target_frame": "su2",
        "matrix": [[0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        "scale": 1.0,
        "translation_m": [0.0, 0.0, 0.0],
    }
    assert "angle_of_attack" not in json.dumps(record)
    assert json.loads(json.dumps(record)) == record


def test_zero_degree_lift_axis_is_positive_su2_z_and_source_is_unchanged():
    original_up = [0.0, 1.0, 0.0]

    mapped_up = ORIGINAL_TO_SU2_TRANSFORM.apply(original_up)

    assert mapped_up == (0.0, 0.0, 1.0)
    assert original_up == [0.0, 1.0, 0.0]
