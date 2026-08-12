"""Immutable, tag-free records for external-flow mesh generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Mapping

from phoenix_aero_lite.models.errors import ValidationIssue
from phoenix_aero_lite.models.geometry import BoundingBox, Vector3
from phoenix_aero_lite.models.parameters import (
    FlowParameters,
    MeshMode,
    MeshParameters,
    ReferenceParameters,
)


_MESH_ISSUE_TEXT_ZH: dict[str, str] = {
    "MODEL_SOURCE_MISSING": "STEP 源文件不存在或不是常规文件。",
    "MODEL_SOURCE_EMPTY": "STEP 源文件不能为空。",
    "MODEL_STEP_IMPORT_FAILED": "Gmsh OpenCASCADE 无法导入 STEP 几何。",
    "MODEL_STEP_NO_VOLUMES": "STEP 几何不包含可用的三维实体。",
    "MODEL_STEP_MULTIPLE_VOLUMES": "STEP 几何必须只包含一个三维实体。",
    "MODEL_STEP_NON_POSITIVE_VOLUME": "STEP 三维实体的体积必须大于零。",
    "MODEL_STEP_OPEN_SHELL": "STEP 三维实体不是封闭壳体。",
    "MODEL_SCALE_OUT_OF_RANGE": "映射后的机体长度超出允许的米制范围。",
    "FLUID_VOLUME_INVALID": "外流场布尔差必须产生一个流体体积。",
    "AIRCRAFT_BOUNDARY_LOST": "布尔差后无法识别机体边界。",
    "FARFIELD_BOUNDARY_LOST": "布尔差后无法识别远场边界。",
    "BOUNDARY_GROUPS_OVERLAP": "机体与远场边界分组发生重叠。",
    "PHYSICAL_GROUP_EMPTY": "必需的物理分组缺失或为空。",
    "NON_MANIFOLD_MESH": "网格包含由三个或更多体单元共享的非流形面。",
    "MESH_HAS_NO_VOLUME_ELEMENTS": "网格不包含三维体单元。",
    "NEGATIVE_ELEMENT_QUALITY": "网格包含负质量或负雅可比单元。",
    "RESOURCE_NODE_LIMIT_EXCEEDED": "网格节点数超过资源上限。",
    "RESOURCE_CELL_LIMIT_EXCEEDED": "网格单元数超过资源上限。",
    "RESOURCE_MEMORY_LIMIT_EXCEEDED": "网格估算内存超过资源上限。",
    "NEAR_WALL_LAYER_NOT_VALIDATED": "近壁三维层网格尚未通过合成封闭实体验证。",
    "NEAR_WALL_DESIGN_REYNOLDS_OUT_OF_RANGE": "当前雷诺数不适合使用已审计的湍流平板近壁估算。",
    "MESH_GENERATION_FAILED": "Gmsh 无法生成外流场网格。",
    "MESH_INVALID_SURFACE_ELEMENTS": "Gmsh 报告机体曲面仍含无效表面单元，已阻止工程求解。",
    "MESH_ARTIFACT_WRITE_FAILED": "网格工件写入失败。",
    "MESH_ARTIFACT_ROUNDTRIP_FAILED": "网格工件回读验证失败。",
    "MESH_BOUNDARY_INCIDENCE_INVALID": "体网格外表面标记或层间接口不完整。",
    "SU2_VALIDATOR_REQUIRED": "必须显式提供官方 SU2 语义验证器的绝对路径。",
    "SU2_VALIDATOR_PATH_NOT_ABSOLUTE": "SU2 语义验证器路径必须为绝对路径。",
    "SU2_VALIDATOR_NOT_FOUND": "SU2 语义验证器路径不存在或不是常规文件。",
    "SU2_VALIDATOR_NAME_INVALID": "SU2 语义验证器文件名必须为 SU2_CFD.exe。",
    "SU2_VALIDATOR_LAUNCH_FAILED": "SU2 语义验证器无法安全启动。",
    "SU2_VALIDATOR_VERSION_UNSUPPORTED": "SU2 语义验证器必须为官方 8.5.0 版本。",
}


class MeshingError(ValueError):
    """Stable validation failure at the external-meshing boundary."""

    def __init__(self, code: str, text_zh: str | None = None) -> None:
        self.issue = ValidationIssue(
            code=code,
            text_zh=_MESH_ISSUE_TEXT_ZH[code] if text_zh is None else text_zh,
        )
        self.issues = (self.issue,)
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExternalDomain:
    """Approved farfield extents derived from mapped aircraft bounds."""

    aircraft_bounds_m: BoundingBox
    outer_bounds_m: BoundingBox
    reference_length_m: float

    @classmethod
    def around_aircraft(cls, aircraft_bounds_m: BoundingBox) -> "ExternalDomain":
        """Build the 3L-upstream/8L-downstream/4L-side domain."""

        minimum = aircraft_bounds_m.minimum_m
        maximum = aircraft_bounds_m.maximum_m
        reference_length = maximum[0] - minimum[0]
        if not math.isfinite(reference_length) or not 1.0e-4 <= reference_length <= 1.0e3:
            raise MeshingError("MODEL_SCALE_OUT_OF_RANGE")
        outer = BoundingBox(
            minimum_m=(
                minimum[0] - 3.0 * reference_length,
                minimum[1] - 4.0 * reference_length,
                minimum[2] - 4.0 * reference_length,
            ),
            maximum_m=(
                maximum[0] + 8.0 * reference_length,
                maximum[1] + 4.0 * reference_length,
                maximum[2] + 4.0 * reference_length,
            ),
        )
        return cls(
            aircraft_bounds_m=aircraft_bounds_m,
            outer_bounds_m=outer,
            reference_length_m=reference_length,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "aircraft_bounds_m": _bounds_to_dict(self.aircraft_bounds_m),
            "outer_bounds_m": _bounds_to_dict(self.outer_bounds_m),
            "reference_length_m": self.reference_length_m,
        }


@dataclass(frozen=True, slots=True)
class NearWallDesignEvidence:
    """Physics inputs and provenance for an estimated first-cell height."""

    target_y_plus: float
    turbulence_model: str
    wall_function_used: bool
    reynolds_number: float
    skin_friction_coefficient: float
    friction_velocity_m_s: float
    skin_friction_method: str
    evidence_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "target_y_plus": self.target_y_plus,
            "turbulence_model": self.turbulence_model,
            "wall_function_used": self.wall_function_used,
            "reynolds_number": self.reynolds_number,
            "skin_friction_coefficient": self.skin_friction_coefficient,
            "friction_velocity_m_s": self.friction_velocity_m_s,
            "skin_friction_method": self.skin_friction_method,
            "evidence_status": self.evidence_status,
        }


@dataclass(frozen=True, slots=True)
class MeshingStrategy:
    """Every deterministic mesh-size, layer and resource decision."""

    mode: MeshMode
    target_cell_size_m: float
    aircraft_size_min_m: float
    aircraft_size_max_m: float
    aircraft_refinement_distance_min_m: float
    aircraft_refinement_distance_max_m: float
    wake_size_m: float
    farfield_size_m: float
    near_wall_layers_required: bool
    near_wall_layers_present: bool
    near_wall_layer_count: int
    near_wall_first_height_m: float
    near_wall_growth_ratio: float
    near_wall_total_thickness_m: float
    drag_fidelity: str
    max_nodes: int
    max_cells: int
    max_estimated_memory_bytes: int
    near_wall_design: NearWallDesignEvidence | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "target_cell_size_m": self.target_cell_size_m,
            "aircraft_size_min_m": self.aircraft_size_min_m,
            "aircraft_size_max_m": self.aircraft_size_max_m,
            "aircraft_refinement_distance_min_m": self.aircraft_refinement_distance_min_m,
            "aircraft_refinement_distance_max_m": self.aircraft_refinement_distance_max_m,
            "wake_size_m": self.wake_size_m,
            "farfield_size_m": self.farfield_size_m,
            "near_wall_layers_required": self.near_wall_layers_required,
            "near_wall_layers_present": self.near_wall_layers_present,
            "near_wall_layer_count": self.near_wall_layer_count,
            "near_wall_first_height_m": self.near_wall_first_height_m,
            "near_wall_growth_ratio": self.near_wall_growth_ratio,
            "near_wall_total_thickness_m": self.near_wall_total_thickness_m,
            "drag_fidelity": self.drag_fidelity,
            "max_nodes": self.max_nodes,
            "max_cells": self.max_cells,
            "max_estimated_memory_bytes": self.max_estimated_memory_bytes,
            "near_wall_design": (
                self.near_wall_design.to_dict()
                if self.near_wall_design is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PhysicalGroupSummary:
    """Durable physical-group identity without transient Gmsh entity tags."""

    name: str
    dimension: int
    entity_count: int
    bounding_boxes_m: tuple[BoundingBox, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "dimension": self.dimension,
            "entity_count": self.entity_count,
            "bounding_boxes_m": [_bounds_to_dict(bounds) for bounds in self.bounding_boxes_m],
        }


@dataclass(frozen=True, slots=True)
class QualityStatistics:
    """Distribution and worst-cell evidence for signed mesh quality."""

    minimum: float
    mean: float
    first_percentile: float
    worst_element_tag: int | None
    worst_element_centroid_m: Vector3 | None
    negative_count: int


@dataclass(frozen=True, slots=True)
class NearWallLayerEvidence:
    """Measured proof for an official three-dimensional layer extrusion."""

    api_path: str
    gmsh_version: str
    source_face_count: int
    layer_element_count: int
    validated_layer_count: int
    measured_first_height_m: float
    measured_growth_ratio: float
    measured_total_thickness_m: float
    minimum_jacobian: float
    minimum_volume: float
    negative_jacobian_count: int
    negative_volume_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "api_path": self.api_path,
            "gmsh_version": self.gmsh_version,
            "source_face_count": self.source_face_count,
            "layer_element_count": self.layer_element_count,
            "validated_layer_count": self.validated_layer_count,
            "measured_first_height_m": self.measured_first_height_m,
            "measured_growth_ratio": self.measured_growth_ratio,
            "measured_total_thickness_m": self.measured_total_thickness_m,
            "minimum_jacobian": self.minimum_jacobian,
            "minimum_volume": self.minimum_volume,
            "negative_jacobian_count": self.negative_jacobian_count,
            "negative_volume_count": self.negative_volume_count,
        }


@dataclass(frozen=True, slots=True)
class WholeMeshValidityEvidence:
    """Signed volume/Jacobian proof covering every generated 3D cell."""

    cell_count: int
    minimum_jacobian: float
    minimum_volume: float
    non_finite_jacobian_count: int
    non_finite_volume_count: int
    non_positive_jacobian_count: int
    non_positive_volume_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "cell_count": self.cell_count,
            "minimum_jacobian": self.minimum_jacobian,
            "minimum_volume": self.minimum_volume,
            "non_finite_jacobian_count": self.non_finite_jacobian_count,
            "non_finite_volume_count": self.non_finite_volume_count,
            "non_positive_jacobian_count": self.non_positive_jacobian_count,
            "non_positive_volume_count": self.non_positive_volume_count,
        }


@dataclass(frozen=True, slots=True)
class FaceIncidenceEvidence:
    """Complete external-marker and internal-interface incidence proof."""

    external_face_count: int
    internal_face_count: int
    aircraft_face_count: int
    farfield_face_count: int
    unmarked_external_face_count: int
    multiply_marked_external_face_count: int
    tagged_internal_face_count: int
    nonconformal_face_count: int
    layer_interface_face_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "external_face_count": self.external_face_count,
            "internal_face_count": self.internal_face_count,
            "aircraft_face_count": self.aircraft_face_count,
            "farfield_face_count": self.farfield_face_count,
            "unmarked_external_face_count": self.unmarked_external_face_count,
            "multiply_marked_external_face_count": (
                self.multiply_marked_external_face_count
            ),
            "tagged_internal_face_count": self.tagged_internal_face_count,
            "nonconformal_face_count": self.nonconformal_face_count,
            "layer_interface_face_count": self.layer_interface_face_count,
        }


@dataclass(frozen=True, slots=True)
class MeshQualityReport:
    """Auditable quality and resource result for a generated mesh."""

    node_count: int
    cell_count: int
    element_type_counts: tuple[tuple[str, int], ...]
    minimum_quality: float
    mean_quality: float
    first_percentile_quality: float
    worst_element_tag: int | None
    worst_element_centroid_m: Vector3 | None
    negative_quality_count: int
    boundary_face_counts: tuple[tuple[str, int], ...]
    physical_group_presence: tuple[tuple[str, bool], ...]
    non_manifold_face_count: int
    estimated_memory_bytes: int
    max_nodes: int
    max_cells: int
    max_estimated_memory_bytes: int
    near_wall_layers_required: bool
    near_wall_layers_present: bool
    near_wall_layer_count: int
    near_wall_first_height_m: float
    near_wall_growth_ratio: float
    near_wall_total_thickness_m: float
    drag_fidelity: str
    near_wall_evidence: NearWallLayerEvidence | None
    whole_mesh_validity: WholeMeshValidityEvidence | None = None
    face_incidence: FaceIncidenceEvidence | None = None
    near_wall_design: NearWallDesignEvidence | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_count": self.node_count,
            "cell_count": self.cell_count,
            "element_type_counts": dict(self.element_type_counts),
            "minimum_quality": self.minimum_quality,
            "mean_quality": self.mean_quality,
            "first_percentile_quality": self.first_percentile_quality,
            "worst_element_tag": self.worst_element_tag,
            "worst_element_centroid_m": (
                list(self.worst_element_centroid_m)
                if self.worst_element_centroid_m is not None
                else None
            ),
            "negative_quality_count": self.negative_quality_count,
            "boundary_face_counts": dict(self.boundary_face_counts),
            "physical_group_presence": dict(self.physical_group_presence),
            "non_manifold_face_count": self.non_manifold_face_count,
            "estimated_memory_bytes": self.estimated_memory_bytes,
            "ceilings": {
                "max_nodes": self.max_nodes,
                "max_cells": self.max_cells,
                "max_estimated_memory_bytes": self.max_estimated_memory_bytes,
            },
            "near_wall": {
                "required": self.near_wall_layers_required,
                "present": self.near_wall_layers_present,
                "layer_count": self.near_wall_layer_count,
                "first_height_m": self.near_wall_first_height_m,
                "growth_ratio": self.near_wall_growth_ratio,
                "total_thickness_m": self.near_wall_total_thickness_m,
                "drag_fidelity": self.drag_fidelity,
                "design": (
                    self.near_wall_design.to_dict()
                    if self.near_wall_design is not None
                    else None
                ),
                "validation": (
                    self.near_wall_evidence.to_dict()
                    if self.near_wall_evidence is not None
                    else None
                ),
            },
            "whole_mesh_validity": (
                self.whole_mesh_validity.to_dict()
                if self.whole_mesh_validity is not None
                else None
            ),
            "face_incidence": (
                self.face_incidence.to_dict()
                if self.face_incidence is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class MeshArtifacts:
    """Paths and durable evidence produced by one successful mesh build."""

    msh_path: Path
    su2_path: Path
    vtu_path: Path
    mapping_json_path: Path
    quality_json_path: Path
    domain: ExternalDomain
    strategy: MeshingStrategy
    physical_groups: tuple[PhysicalGroupSummary, ...]
    quality: MeshQualityReport


def derive_meshing_strategy(
    mesh_parameters: MeshParameters,
    *,
    max_nodes: int = 2_000_000,
    max_cells: int = 10_000_000,
    max_estimated_memory_bytes: int = 4 * 1024**3,
) -> MeshingStrategy:
    """Derive all mesh controls solely from mode and target size."""

    issues = mesh_parameters.validate()
    if issues:
        raise MeshingError(issues[0].code, issues[0].text_zh)
    if max_nodes <= 0 or max_cells <= 0 or max_estimated_memory_bytes <= 0:
        raise ValueError("resource ceilings must be positive")

    target = float(mesh_parameters.target_cell_size_m)
    values: Mapping[MeshMode, tuple[float, float, float, float, int, float, float]] = {
        MeshMode.PREVIEW: (0.5, 1.0, 0.75, 2.0, 0, 0.0, 0.0),
        MeshMode.STANDARD: (0.3, 0.75, 0.5, 1.5, 5, 1.0 / 20.0, 1.2),
        MeshMode.FINE: (0.2, 0.5, 0.35, 1.0, 8, 1.0 / 40.0, 1.18),
    }
    aircraft_min, aircraft_max, wake, farfield, layers, first_factor, growth = values[
        mesh_parameters.mode
    ]
    first_height = target * first_factor
    total_thickness = (
        first_height * (growth**layers - 1.0) / (growth - 1.0) if layers else 0.0
    )
    requires_layers = layers > 0
    return MeshingStrategy(
        mode=mesh_parameters.mode,
        target_cell_size_m=target,
        aircraft_size_min_m=target * aircraft_min,
        aircraft_size_max_m=target * aircraft_max,
        aircraft_refinement_distance_min_m=target,
        aircraft_refinement_distance_max_m=3.0 * target,
        wake_size_m=target * wake,
        farfield_size_m=target * farfield,
        near_wall_layers_required=requires_layers,
        near_wall_layers_present=False,
        near_wall_layer_count=layers,
        near_wall_first_height_m=first_height,
        near_wall_growth_ratio=growth,
        near_wall_total_thickness_m=total_thickness,
        drag_fidelity=(
            "requires_validated_near_wall_layers" if requires_layers else "preview_only"
        ),
        max_nodes=max_nodes,
        max_cells=max_cells,
        max_estimated_memory_bytes=max_estimated_memory_bytes,
    )


def apply_near_wall_design(
    strategy: MeshingStrategy,
    *,
    flow: FlowParameters,
    reference: ReferenceParameters,
    target_y_plus: float,
    turbulence_model: str,
    wall_function_used: bool,
) -> MeshingStrategy:
    """Replace size-based layer spacing with an auditable Y+ estimate.

    The result is explicitly ``estimated``.  Only post-solve wall output can
    provide the computed Y+ evidence used by the credibility gate.
    """

    if not strategy.near_wall_layers_required:
        return strategy
    if flow.validate() or reference.validate():
        raise MeshingError("NEAR_WALL_DESIGN_REYNOLDS_OUT_OF_RANGE")
    if (
        not isinstance(target_y_plus, (int, float))
        or isinstance(target_y_plus, bool)
        or not math.isfinite(target_y_plus)
        or target_y_plus <= 0.0
        or not turbulence_model
        or not isinstance(wall_function_used, bool)
    ):
        raise ValueError("NEAR_WALL_DESIGN_INPUT_INVALID")
    reynolds = (
        flow.density_kg_m3
        * flow.velocity_m_s
        * reference.c_ref_m
        / flow.dynamic_viscosity_pa_s
    )
    if not math.isfinite(reynolds) or reynolds < 1.0e4:
        raise MeshingError("NEAR_WALL_DESIGN_REYNOLDS_OUT_OF_RANGE")
    skin_friction = 0.026 / reynolds ** (1.0 / 7.0)
    friction_velocity = flow.velocity_m_s * math.sqrt(skin_friction / 2.0)
    first_height = (
        float(target_y_plus)
        * flow.dynamic_viscosity_pa_s
        / (flow.density_kg_m3 * friction_velocity)
    )
    growth = strategy.near_wall_growth_ratio
    layers = strategy.near_wall_layer_count
    total_thickness = first_height * (growth**layers - 1.0) / (growth - 1.0)
    design = NearWallDesignEvidence(
        target_y_plus=float(target_y_plus),
        turbulence_model=str(turbulence_model),
        wall_function_used=wall_function_used,
        reynolds_number=reynolds,
        skin_friction_coefficient=skin_friction,
        friction_velocity_m_s=friction_velocity,
        skin_friction_method=(
            "NASA TMR turbulent flat-plate estimate Cf=0.026/Re^(1/7)"
        ),
        evidence_status="estimated",
    )
    return replace(
        strategy,
        near_wall_first_height_m=first_height,
        near_wall_total_thickness_m=total_thickness,
        near_wall_design=design,
    )


def _bounds_to_dict(bounds: BoundingBox) -> dict[str, list[float]]:
    return {
        "minimum_m": list(bounds.minimum_m),
        "maximum_m": list(bounds.maximum_m),
    }
