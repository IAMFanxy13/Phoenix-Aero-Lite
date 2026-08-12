"""Unit contracts for deterministic mesh strategy and quality gates."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from phoenix_aero_lite.meshing.mesh_quality import (
    build_quality_report,
    calculate_quality_statistics,
    enforce_resource_limits,
    estimate_mesh_memory_bytes,
)
from phoenix_aero_lite.models.geometry import BoundingBox
from phoenix_aero_lite.models.mesh import (
    ExternalDomain,
    MeshingError,
    apply_near_wall_design,
    derive_meshing_strategy,
)
from phoenix_aero_lite.models.parameters import (
    FlowParameters,
    MeshMode,
    MeshParameters,
    ReferenceParameters,
)


def test_external_domain_uses_the_approved_reference_length_extents():
    aircraft = BoundingBox(minimum_m=(-2.0, -1.0, -0.5), maximum_m=(3.0, 2.0, 0.75))

    domain = ExternalDomain.around_aircraft(aircraft)

    assert domain.reference_length_m == pytest.approx(5.0)
    assert domain.outer_bounds_m.minimum_m == pytest.approx((-17.0, -21.0, -20.5))
    assert domain.outer_bounds_m.maximum_m == pytest.approx((43.0, 22.0, 20.75))
    assert domain.aircraft_bounds_m == aircraft


@pytest.mark.parametrize(
    "bounds",
    [
        BoundingBox((0.0, 0.0, 0.0), (1.0e-7, 1.0, 1.0)),
        BoundingBox((0.0, 0.0, 0.0), (1.0e4, 1.0, 1.0)),
        BoundingBox((1.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
    ],
)
def test_external_domain_rejects_out_of_range_or_zero_reference_length(bounds):
    with pytest.raises(MeshingError) as error:
        ExternalDomain.around_aircraft(bounds)

    assert error.value.issue.code == "MODEL_SCALE_OUT_OF_RANGE"
    assert error.value.issue.text_zh


def test_preview_strategy_is_deterministic_and_declares_preview_only_drag():
    strategy = derive_meshing_strategy(MeshParameters(MeshMode.PREVIEW, 0.2))

    assert strategy.aircraft_size_min_m == pytest.approx(0.1)
    assert strategy.aircraft_size_max_m == pytest.approx(0.2)
    assert strategy.aircraft_refinement_distance_min_m == pytest.approx(0.2)
    assert strategy.aircraft_refinement_distance_max_m == pytest.approx(0.6)
    assert strategy.wake_size_m == pytest.approx(0.15)
    assert strategy.farfield_size_m == pytest.approx(0.4)
    assert strategy.near_wall_layers_present is False
    assert strategy.near_wall_layer_count == 0
    assert strategy.drag_fidelity == "preview_only"


@pytest.mark.parametrize(
    ("mode", "layer_count", "growth_ratio", "first_height_factor"),
    [
        (MeshMode.STANDARD, 5, 1.2, 1.0 / 20.0),
        (MeshMode.FINE, 8, 1.18, 1.0 / 40.0),
    ],
)
def test_standard_and_fine_strategy_record_the_full_required_layer_declaration(
    mode, layer_count, growth_ratio, first_height_factor
):
    strategy = derive_meshing_strategy(MeshParameters(mode, 0.2))

    expected_first = 0.2 * first_height_factor
    expected_total = expected_first * (growth_ratio**layer_count - 1.0) / (growth_ratio - 1.0)
    assert strategy.near_wall_layers_required is True
    assert strategy.near_wall_layers_present is False
    assert strategy.near_wall_layer_count == layer_count
    assert strategy.near_wall_first_height_m == pytest.approx(expected_first)
    assert strategy.near_wall_growth_ratio == pytest.approx(growth_ratio)
    assert strategy.near_wall_total_thickness_m == pytest.approx(expected_total)
    assert strategy.drag_fidelity == "requires_validated_near_wall_layers"


def test_near_wall_design_uses_reynolds_target_yplus_and_explicit_friction_method():
    strategy = derive_meshing_strategy(MeshParameters(MeshMode.STANDARD, 0.2))
    flow = FlowParameters(
        velocity_m_s=15.0,
        density_kg_m3=1.225,
        dynamic_viscosity_pa_s=1.789e-5,
        angle_of_attack_deg=6.0,
    )

    designed = apply_near_wall_design(
        strategy,
        flow=flow,
        reference=ReferenceParameters(s_ref_m2=1.0, c_ref_m=0.5),
        target_y_plus=1.0,
        turbulence_model="SST",
        wall_function_used=False,
    )

    reynolds = 1.225 * 15.0 * 0.5 / 1.789e-5
    skin_friction = 0.026 / reynolds ** (1.0 / 7.0)
    friction_velocity = 15.0 * (skin_friction / 2.0) ** 0.5
    expected_first_height = 1.0 * 1.789e-5 / (1.225 * friction_velocity)
    assert designed.near_wall_first_height_m == pytest.approx(expected_first_height)
    assert designed.near_wall_total_thickness_m == pytest.approx(
        expected_first_height
        * (designed.near_wall_growth_ratio**designed.near_wall_layer_count - 1.0)
        / (designed.near_wall_growth_ratio - 1.0)
    )
    assert designed.near_wall_design is not None
    assert designed.near_wall_design.target_y_plus == 1.0
    assert designed.near_wall_design.reynolds_number == pytest.approx(reynolds)
    assert designed.near_wall_design.skin_friction_coefficient == pytest.approx(
        skin_friction
    )
    assert designed.near_wall_design.turbulence_model == "SST"
    assert designed.near_wall_design.wall_function_used is False
    assert designed.near_wall_design.evidence_status == "estimated"
    assert designed.near_wall_design.skin_friction_method == (
        "NASA TMR turbulent flat-plate estimate Cf=0.026/Re^(1/7)"
    )


def test_mesh_records_are_immutable():
    domain = ExternalDomain.around_aircraft(BoundingBox((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))

    with pytest.raises(FrozenInstanceError):
        domain.reference_length_m = 2.0


def test_quality_statistics_include_lower_tail_and_worst_element_evidence():
    statistics = calculate_quality_statistics(
        [0.8, 0.4, 0.9, 0.2],
        element_tags=[11, 12, 13, 14],
        centroids=[(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (4.0, 0.0, 0.0)],
    )

    assert statistics.minimum == pytest.approx(0.2)
    assert statistics.mean == pytest.approx(0.575)
    assert statistics.first_percentile == pytest.approx(0.206)
    assert statistics.worst_element_tag == 14
    assert statistics.worst_element_centroid_m == pytest.approx((4.0, 0.0, 0.0))
    assert statistics.negative_count == 0


def test_quality_statistics_reject_empty_input():
    with pytest.raises(MeshingError) as error:
        calculate_quality_statistics([])

    assert error.value.issue.code == "MESH_HAS_NO_VOLUME_ELEMENTS"


def test_quality_report_rejects_negative_quality():
    strategy = derive_meshing_strategy(MeshParameters(MeshMode.PREVIEW, 0.2))

    with pytest.raises(MeshingError) as error:
        build_quality_report(
            node_count=20,
            element_type_counts={"tetrahedron": 4},
            qualities=[0.2, -0.01, 0.5, 0.8],
            element_tags=[1, 2, 3, 4],
            centroids=[(0.0, 0.0, 0.0)] * 4,
            boundary_face_counts={"aircraft": 4, "farfield": 6},
            physical_group_counts={"fluid": 1, "aircraft": 1, "farfield": 6},
            strategy=strategy,
        )

    assert error.value.issue.code == "NEGATIVE_ELEMENT_QUALITY"


def test_quality_report_rejects_non_manifold_volume_faces():
    strategy = derive_meshing_strategy(MeshParameters(MeshMode.PREVIEW, 0.2))

    with pytest.raises(MeshingError) as error:
        build_quality_report(
            node_count=20,
            element_type_counts={"tetrahedron": 1},
            qualities=[0.5],
            element_tags=[1],
            centroids=[(0.0, 0.0, 0.0)],
            boundary_face_counts={"aircraft": 4, "farfield": 6},
            physical_group_counts={"fluid": 1, "aircraft": 1, "farfield": 6},
            strategy=strategy,
            non_manifold_face_count=1,
        )

    assert error.value.issue.code == "NON_MANIFOLD_MESH"


def test_quality_report_records_near_wall_and_non_manifold_declarations():
    strategy = derive_meshing_strategy(MeshParameters(MeshMode.PREVIEW, 0.2))

    report = build_quality_report(
        node_count=20,
        element_type_counts={"tetrahedron": 1},
        qualities=[0.5],
        element_tags=[1],
        centroids=[(0.0, 0.0, 0.0)],
        boundary_face_counts={"aircraft": 4, "farfield": 6},
        physical_group_counts={"fluid": 1, "aircraft": 1, "farfield": 6},
        strategy=strategy,
        non_manifold_face_count=0,
    )

    assert report.non_manifold_face_count == 0
    assert report.to_dict()["near_wall"] == {
        "required": False,
        "present": False,
        "layer_count": 0,
        "first_height_m": 0.0,
        "growth_ratio": 0.0,
        "total_thickness_m": 0.0,
        "drag_fidelity": "preview_only",
        "design": None,
        "validation": None,
    }


@pytest.mark.parametrize("mode", [MeshMode.STANDARD, MeshMode.FINE])
def test_quality_report_refuses_required_layers_without_validation_evidence(mode):
    strategy = derive_meshing_strategy(MeshParameters(mode, 0.2))

    with pytest.raises(MeshingError) as error:
        build_quality_report(
            node_count=20,
            element_type_counts={"tetrahedron": 1},
            qualities=[0.5],
            element_tags=[1],
            centroids=[(0.0, 0.0, 0.0)],
            boundary_face_counts={"aircraft": 4, "farfield": 6},
            physical_group_counts={"fluid": 1, "aircraft": 1, "farfield": 6},
            strategy=strategy,
        )

    assert error.value.issue.code == "NEAR_WALL_LAYER_NOT_VALIDATED"


def test_invalid_mesh_parameters_preserve_the_parameter_issue():
    with pytest.raises(MeshingError) as error:
        derive_meshing_strategy(MeshParameters(MeshMode.PREVIEW, 0.0))

    assert error.value.issue.code == "MESH_TARGET_CELL_SIZE_MUST_BE_POSITIVE"
    assert error.value.issue.text_zh


@pytest.mark.parametrize("missing_name", ["fluid", "aircraft", "farfield"])
def test_quality_report_rejects_missing_or_empty_required_groups(missing_name):
    strategy = derive_meshing_strategy(MeshParameters(MeshMode.PREVIEW, 0.2))
    groups = {"fluid": 1, "aircraft": 1, "farfield": 6}
    groups[missing_name] = 0

    with pytest.raises(MeshingError) as error:
        build_quality_report(
            node_count=20,
            element_type_counts={"tetrahedron": 1},
            qualities=[0.5],
            element_tags=[1],
            centroids=[(0.0, 0.0, 0.0)],
            boundary_face_counts={"aircraft": 4, "farfield": 6},
            physical_group_counts=groups,
            strategy=strategy,
        )

    assert error.value.issue.code == "PHYSICAL_GROUP_EMPTY"


def test_resource_limits_are_checked_against_all_three_ceilings():
    strategy = derive_meshing_strategy(
        MeshParameters(MeshMode.PREVIEW, 0.2),
        max_nodes=100,
        max_cells=200,
        max_estimated_memory_bytes=10_000,
    )

    enforce_resource_limits(
        node_count=100,
        cell_count=200,
        estimated_memory_bytes=10_000,
        strategy=strategy,
    )

    cases = [
        (101, 1, 1, "RESOURCE_NODE_LIMIT_EXCEEDED"),
        (1, 201, 1, "RESOURCE_CELL_LIMIT_EXCEEDED"),
        (1, 1, 10_001, "RESOURCE_MEMORY_LIMIT_EXCEEDED"),
    ]
    for node_count, cell_count, memory, code in cases:
        with pytest.raises(MeshingError) as error:
            enforce_resource_limits(
                node_count=node_count,
                cell_count=cell_count,
                estimated_memory_bytes=memory,
                strategy=strategy,
            )
        assert error.value.issue.code == code


def test_memory_estimate_is_deterministic_and_positive():
    assert estimate_mesh_memory_bytes(node_count=10, cell_count=20) == 4160
