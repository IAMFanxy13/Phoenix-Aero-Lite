"""Tag-free mesh quality statistics and deterministic resource gates."""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from phoenix_aero_lite.models.geometry import Vector3
from phoenix_aero_lite.models.mesh import (
    MeshQualityReport,
    MeshingError,
    MeshingStrategy,
    FaceIncidenceEvidence,
    NearWallLayerEvidence,
    QualityStatistics,
    WholeMeshValidityEvidence,
)


_BYTES_PER_NODE = 96
_BYTES_PER_CELL = 160
_REQUIRED_GROUP_NAMES = ("fluid", "aircraft", "farfield")


def estimate_mesh_memory_bytes(*, node_count: int, cell_count: int) -> int:
    """Return a conservative, deterministic in-process memory estimate."""

    return max(0, node_count) * _BYTES_PER_NODE + max(0, cell_count) * _BYTES_PER_CELL


def calculate_quality_statistics(
    qualities: Sequence[float],
    *,
    element_tags: Sequence[int] | None = None,
    centroids: Sequence[Vector3] | None = None,
) -> QualityStatistics:
    """Summarize signed cell quality using linear percentile interpolation."""

    if not qualities:
        raise MeshingError("MESH_HAS_NO_VOLUME_ELEMENTS")
    numeric = tuple(float(value) for value in qualities)
    if not all(math.isfinite(value) for value in numeric):
        raise MeshingError("NEGATIVE_ELEMENT_QUALITY")
    worst_index = min(range(len(numeric)), key=numeric.__getitem__)
    ordered = sorted(numeric)
    rank = 0.01 * (len(ordered) - 1)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    fraction = rank - lower_index
    percentile = ordered[lower_index] + fraction * (
        ordered[upper_index] - ordered[lower_index]
    )
    worst_tag = None
    if element_tags is not None:
        if len(element_tags) != len(numeric):
            raise ValueError("element_tags must align with qualities")
        worst_tag = int(element_tags[worst_index])
    worst_centroid = None
    if centroids is not None:
        if len(centroids) != len(numeric):
            raise ValueError("centroids must align with qualities")
        worst_centroid = tuple(float(value) for value in centroids[worst_index])
    return QualityStatistics(
        minimum=min(numeric),
        mean=math.fsum(numeric) / len(numeric),
        first_percentile=percentile,
        worst_element_tag=worst_tag,
        worst_element_centroid_m=worst_centroid,
        negative_count=sum(value < 0.0 for value in numeric),
    )


def enforce_resource_limits(
    *,
    node_count: int,
    cell_count: int,
    estimated_memory_bytes: int,
    strategy: MeshingStrategy,
) -> None:
    """Reject a predicted or generated mesh above any configured ceiling."""

    if node_count > strategy.max_nodes:
        raise MeshingError("RESOURCE_NODE_LIMIT_EXCEEDED")
    if cell_count > strategy.max_cells:
        raise MeshingError("RESOURCE_CELL_LIMIT_EXCEEDED")
    if estimated_memory_bytes > strategy.max_estimated_memory_bytes:
        raise MeshingError("RESOURCE_MEMORY_LIMIT_EXCEEDED")


def build_quality_report(
    *,
    node_count: int,
    element_type_counts: Mapping[str, int],
    qualities: Sequence[float],
    element_tags: Sequence[int],
    centroids: Sequence[Vector3] | None,
    boundary_face_counts: Mapping[str, int],
    physical_group_counts: Mapping[str, int],
    strategy: MeshingStrategy,
    non_manifold_face_count: int = 0,
    near_wall_evidence: NearWallLayerEvidence | None = None,
    whole_mesh_validity: WholeMeshValidityEvidence | None = None,
    face_incidence: FaceIncidenceEvidence | None = None,
) -> MeshQualityReport:
    """Validate required groups, signed quality and resource ceilings."""

    if any(physical_group_counts.get(name, 0) <= 0 for name in _REQUIRED_GROUP_NAMES):
        raise MeshingError("PHYSICAL_GROUP_EMPTY")
    if non_manifold_face_count > 0:
        raise MeshingError("NON_MANIFOLD_MESH")
    if strategy.near_wall_layers_required and (
        not strategy.near_wall_layers_present or near_wall_evidence is None
    ):
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    statistics = calculate_quality_statistics(
        qualities, element_tags=element_tags, centroids=centroids
    )
    if statistics.negative_count:
        raise MeshingError("NEGATIVE_ELEMENT_QUALITY")
    cell_count = sum(int(count) for count in element_type_counts.values())
    estimated_memory = estimate_mesh_memory_bytes(
        node_count=node_count, cell_count=cell_count
    )
    enforce_resource_limits(
        node_count=node_count,
        cell_count=cell_count,
        estimated_memory_bytes=estimated_memory,
        strategy=strategy,
    )
    return MeshQualityReport(
        node_count=node_count,
        cell_count=cell_count,
        element_type_counts=tuple(
            sorted(
                (str(name), int(count)) for name, count in element_type_counts.items()
            )
        ),
        minimum_quality=statistics.minimum,
        mean_quality=statistics.mean,
        first_percentile_quality=statistics.first_percentile,
        worst_element_tag=statistics.worst_element_tag,
        worst_element_centroid_m=statistics.worst_element_centroid_m,
        negative_quality_count=statistics.negative_count,
        boundary_face_counts=tuple(
            sorted((str(name), int(count)) for name, count in boundary_face_counts.items())
        ),
        physical_group_presence=tuple(
            (name, physical_group_counts.get(name, 0) > 0) for name in _REQUIRED_GROUP_NAMES
        ),
        non_manifold_face_count=non_manifold_face_count,
        estimated_memory_bytes=estimated_memory,
        max_nodes=strategy.max_nodes,
        max_cells=strategy.max_cells,
        max_estimated_memory_bytes=strategy.max_estimated_memory_bytes,
        near_wall_layers_required=strategy.near_wall_layers_required,
        near_wall_layers_present=strategy.near_wall_layers_present,
        near_wall_layer_count=strategy.near_wall_layer_count,
        near_wall_first_height_m=strategy.near_wall_first_height_m,
        near_wall_growth_ratio=strategy.near_wall_growth_ratio,
        near_wall_total_thickness_m=strategy.near_wall_total_thickness_m,
        drag_fidelity=strategy.drag_fidelity,
        near_wall_evidence=near_wall_evidence,
        whole_mesh_validity=whole_mesh_validity,
        face_incidence=face_incidence,
        near_wall_design=strategy.near_wall_design,
    )
