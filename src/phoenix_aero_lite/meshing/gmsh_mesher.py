"""Bounded Gmsh/OpenCASCADE adapter for tagged external-flow meshes."""

from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Iterator, Sequence
from uuid import uuid4

import gmsh
import meshio

from phoenix_aero_lite.meshing.mesh_quality import (
    build_quality_report,
    enforce_resource_limits,
    estimate_mesh_memory_bytes,
)
from phoenix_aero_lite.models.geometry import BoundingBox, Vector3
from phoenix_aero_lite.models.mesh import (
    ExternalDomain,
    FaceIncidenceEvidence,
    MeshArtifacts,
    MeshingError,
    MeshingStrategy,
    NearWallLayerEvidence,
    PhysicalGroupSummary,
    WholeMeshValidityEvidence,
    apply_near_wall_design,
    derive_meshing_strategy,
)
from phoenix_aero_lite.models.parameters import (
    FlowParameters,
    MeshParameters,
    ReferenceParameters,
)


_OCC_TARGET_UNIT = "M"
_SU2_VALIDATOR_FILENAME = "SU2_CFD.exe"
_SU2_VALIDATOR_VERSION = "8.5.0"
_VALIDATED_NEAR_WALL_GMSH_VERSION = "4.15.2"
_NEAR_WALL_API_PATH = "gmsh.model.geo.extrudeBoundaryLayer"
_AFFINE_ORIGINAL_TO_SU2 = (
    0.0,
    0.0,
    -1.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
)
_NUMBER_OPTIONS = (
    "General.Terminal",
    "Mesh.MeshSizeMin",
    "Mesh.MeshSizeMax",
    "Mesh.MeshSizeExtendFromBoundary",
    "Mesh.MeshSizeFromPoints",
    "Mesh.MeshSizeFromCurvature",
    "Mesh.Algorithm3D",
    "Mesh.MaxNumThreads3D",
    "Mesh.MshFileVersion",
    "Mesh.Binary",
    "Mesh.SaveAll",
)
_GMSH_LOCK = RLock()


class GmshMesher:
    """Generate Preview meshes while enforcing explicit resource ceilings."""

    def __init__(
        self,
        *,
        su2_validator_path: Path | None = None,
        max_nodes: int = 2_000_000,
        max_cells: int = 10_000_000,
        max_estimated_memory_bytes: int = 4 * 1024**3,
    ) -> None:
        if su2_validator_path is None:
            raise MeshingError("SU2_VALIDATOR_REQUIRED")
        if max_nodes <= 0 or max_cells <= 0 or max_estimated_memory_bytes <= 0:
            raise ValueError("resource ceilings must be positive")
        self._su2_validator_path = _validate_su2_validator_path(
            Path(su2_validator_path)
        )
        self._max_nodes = max_nodes
        self._max_cells = max_cells
        self._max_estimated_memory_bytes = max_estimated_memory_bytes

    def build_external_mesh(
        self,
        step_path: Path,
        mesh_parameters: MeshParameters,
        output_directory: Path,
        *,
        flow_parameters: FlowParameters | None = None,
        reference_parameters: ReferenceParameters | None = None,
    ) -> MeshArtifacts:
        """Build a tagged external-flow mesh without exposing Gmsh entity tags."""

        strategy = derive_meshing_strategy(
            mesh_parameters,
            max_nodes=self._max_nodes,
            max_cells=self._max_cells,
            max_estimated_memory_bytes=self._max_estimated_memory_bytes,
        )
        if (flow_parameters is None) != (reference_parameters is None):
            raise ValueError("NEAR_WALL_DESIGN_INPUT_INCOMPLETE")
        if flow_parameters is not None and reference_parameters is not None:
            strategy = apply_near_wall_design(
                strategy,
                flow=flow_parameters,
                reference=reference_parameters,
                target_y_plus=1.0,
                turbulence_model="SST",
                wall_function_used=False,
            )
        if (
            strategy.near_wall_layers_required
            and gmsh.__version__ != _VALIDATED_NEAR_WALL_GMSH_VERSION
        ):
            raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")

        source = Path(step_path)
        if not source.is_file():
            raise MeshingError("MODEL_SOURCE_MISSING")
        if source.stat().st_size == 0:
            raise MeshingError("MODEL_SOURCE_EMPTY")

        try:
            with _meshing_model():
                aircraft_volume = _import_single_closed_solid(source)
                raw_bounds = _bounds_for_entity(3, aircraft_volume)
                # Reject sub-tolerance/implausibly large input before applying an
                # OCC transform: degenerate shapes can otherwise fail inside OCC
                # before a stable scale error can be emitted.
                ExternalDomain.around_aircraft(_mapped_bounds(raw_bounds))
                gmsh.model.occ.affineTransform([(3, aircraft_volume)], _AFFINE_ORIGINAL_TO_SU2)
                gmsh.model.occ.synchronize()
                aircraft_bounds = _bounds_for_entity(3, aircraft_volume)
                domain = ExternalDomain.around_aircraft(aircraft_bounds)
                fluid_volume, aircraft_surfaces, farfield_surfaces = _build_fluid_domain(
                    aircraft_volume, domain
                )
                _enforce_predicted_resources(domain, strategy)
                _configure_preview_mesh_fields(
                    aircraft_surfaces=aircraft_surfaces,
                    domain=domain,
                    strategy=strategy,
                )
                near_wall_evidence = None
                topology = None
                if strategy.near_wall_layers_required:
                    try:
                        topology = _prepare_near_wall_topology(
                            fluid_volume=fluid_volume,
                            aircraft_surfaces=aircraft_surfaces,
                            farfield_surfaces=farfield_surfaces,
                            strategy=strategy,
                        )
                        summaries = _create_physical_groups(
                            topology.fluid_volumes,
                            aircraft_surfaces,
                            farfield_surfaces,
                        )
                        _generate_volume_mesh_checked()
                        _enforce_generated_resources(strategy)
                        whole_mesh_validity = _validate_whole_mesh_cells()
                        near_wall_evidence = _validate_near_wall_mesh(topology, strategy)
                        strategy = replace(
                            strategy,
                            near_wall_layers_present=True,
                            drag_fidelity="validated_near_wall_layers",
                        )
                        summaries = _summarize_physical_groups(
                            topology.fluid_volumes,
                            aircraft_surfaces,
                            farfield_surfaces,
                        )
                    except MeshingError:
                        raise
                    except Exception as error:
                        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED") from error
                else:
                    summaries = _create_physical_groups(
                        (fluid_volume,), aircraft_surfaces, farfield_surfaces
                    )
                    _generate_volume_mesh_checked()
                    _enforce_generated_resources(strategy)
                    whole_mesh_validity = _validate_whole_mesh_cells()
                    summaries = _summarize_physical_groups(
                        (fluid_volume,), aircraft_surfaces, farfield_surfaces
                    )
                face_incidence = _validate_face_incidence(topology, strategy)
                quality = _quality_report(
                    strategy=strategy,
                    aircraft_surfaces=aircraft_surfaces,
                    farfield_surfaces=farfield_surfaces,
                    summaries=summaries,
                    near_wall_evidence=near_wall_evidence,
                    whole_mesh_validity=whole_mesh_validity,
                    face_incidence=face_incidence,
                )
                artifacts = _write_and_verify_artifacts(
                    output_directory=Path(output_directory),
                    su2_validator_path=self._su2_validator_path,
                    domain=domain,
                    strategy=strategy,
                    summaries=summaries,
                    quality=quality,
                )
                (Path(output_directory) / "mesh_failure.json").unlink(
                    missing_ok=True
                )
                return artifacts
        except MeshingError as error:
            _write_mesh_failure_evidence(
                Path(output_directory), source, error
            )
            raise
        except Exception as error:
            raise MeshingError("MESH_GENERATION_FAILED") from error


def _write_mesh_failure_evidence(
    output_directory: Path, source: Path, error: MeshingError
) -> None:
    """Best-effort durable evidence without masking the scientific failure."""

    try:
        output = Path(output_directory).resolve(strict=False)
        output.mkdir(parents=True, exist_ok=True)
        payload = {
            "error_code": error.issue.code,
            "text_zh": error.issue.text_zh,
            "gmsh_messages": list(getattr(error, "gmsh_messages", ())),
            "source": str(source.resolve(strict=True)),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_modified": False,
            "gmsh_version": gmsh.__version__,
        }
        path = output / "mesh_failure.json"
        temporary = output / f".mesh_failure-{uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except (OSError, ValueError):
        return


def _validate_su2_validator_path(candidate: Path) -> Path:
    """Validate an explicitly injected official SU2 8.5.0 executable."""

    if not candidate.is_absolute():
        raise MeshingError("SU2_VALIDATOR_PATH_NOT_ABSOLUTE")
    if not candidate.is_file():
        raise MeshingError("SU2_VALIDATOR_NOT_FOUND")
    if candidate.name.casefold() != _SU2_VALIDATOR_FILENAME.casefold():
        raise MeshingError("SU2_VALIDATOR_NAME_INVALID")
    resolved = candidate.resolve(strict=True)
    try:
        result = subprocess.run(
            [str(resolved), "--help"],
            cwd=resolved.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MeshingError("SU2_VALIDATOR_LAUNCH_FAILED") from error
    banner = f"{result.stdout}\n{result.stderr}"
    version = re.search(r"(?m)^SU2 v(\d+\.\d+\.\d+)(?:\s|$)", banner)
    if version is None or version.group(1) != _SU2_VALIDATOR_VERSION:
        raise MeshingError("SU2_VALIDATOR_VERSION_UNSUPPORTED")
    if result.returncode != 0:
        raise MeshingError("SU2_VALIDATOR_LAUNCH_FAILED")
    return resolved


def _generate_volume_mesh_checked() -> None:
    """Reject Gmsh's explicit invalid-surface warning before SU2 sees the mesh."""

    gmsh.logger.start()
    try:
        gmsh.model.mesh.generate(3)
        messages = tuple(gmsh.logger.get())
    finally:
        gmsh.logger.stop()
    invalid = tuple(
        message for message in messages if "remain invalid" in message.casefold()
    )
    if invalid:
        error = MeshingError("MESH_INVALID_SURFACE_ELEMENTS")
        error.gmsh_messages = invalid
        raise error


def _import_single_closed_solid(step_path: Path) -> int:
    try:
        gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
    except Exception as error:
        raise MeshingError("MODEL_STEP_IMPORT_FAILED") from error
    volumes = gmsh.model.getEntities(3)
    if not volumes:
        if gmsh.model.getEntities(2):
            raise MeshingError("MODEL_STEP_OPEN_SHELL")
        raise MeshingError("MODEL_STEP_NO_VOLUMES")
    if len(volumes) != 1:
        raise MeshingError("MODEL_STEP_MULTIPLE_VOLUMES")
    volume_tag = volumes[0][1]
    volume = float(gmsh.model.occ.getMass(3, volume_tag))
    if not math.isfinite(volume) or volume <= 0.0:
        raise MeshingError("MODEL_STEP_NON_POSITIVE_VOLUME")
    # An imported OCC volume is the closed-solid topology proof. Reapplying the
    # boundary operator to periodic surfaces is not a closure test: valid spheres
    # and cylinders expose parametric seam curves through that query.
    if not gmsh.model.getBoundary(volumes, combined=True, oriented=False):
        raise MeshingError("MODEL_STEP_OPEN_SHELL")
    return volume_tag


def _build_fluid_domain(
    aircraft_volume: int, domain: ExternalDomain
) -> tuple[int, tuple[int, ...], tuple[int, ...]]:
    bounds = domain.outer_bounds_m
    dimensions = bounds.dimensions_m
    box_tag = gmsh.model.occ.addBox(*bounds.minimum_m, *dimensions)
    result, _mapping = gmsh.model.occ.cut(
        [(3, box_tag)],
        [(3, aircraft_volume)],
        removeObject=True,
        removeTool=True,
    )
    gmsh.model.occ.synchronize()
    fluid_volumes = tuple(tag for dimension, tag in result if dimension == 3)
    if len(fluid_volumes) != 1 or len(gmsh.model.getEntities(3)) != 1:
        raise MeshingError("FLUID_VOLUME_INVALID")
    aircraft, farfield = _classify_fluid_boundaries(fluid_volumes[0], bounds)
    return fluid_volumes[0], aircraft, farfield


def _classify_fluid_boundaries(
    fluid_volume: int, outer_bounds_m: BoundingBox
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Reidentify post-Boolean boundaries solely from geometry."""

    boundary_entities = gmsh.model.getBoundary(
        [(3, fluid_volume)], combined=True, oriented=False, recursive=False
    )
    boundary_tags = tuple(
        sorted({abs(tag) for dimension, tag in boundary_entities if dimension == 2})
    )
    tolerance = max(1.0e-8, max(outer_bounds_m.dimensions_m) * 1.0e-7)
    farfield: list[int] = []
    aircraft: list[int] = []
    for surface_tag in boundary_tags:
        bounds = _bounds_for_entity(2, surface_tag)
        touches_outer_plane = any(
            abs(bounds.minimum_m[axis] - outer_bounds_m.minimum_m[axis]) <= tolerance
            or abs(bounds.maximum_m[axis] - outer_bounds_m.maximum_m[axis]) <= tolerance
            for axis in range(3)
        )
        (farfield if touches_outer_plane else aircraft).append(surface_tag)
    if not aircraft:
        raise MeshingError("AIRCRAFT_BOUNDARY_LOST")
    if not farfield:
        raise MeshingError("FARFIELD_BOUNDARY_LOST")
    if set(aircraft) & set(farfield):
        raise MeshingError("BOUNDARY_GROUPS_OVERLAP")
    return tuple(aircraft), tuple(farfield)


@dataclass(frozen=True, slots=True)
class _LayerTopology:
    fluid_volumes: tuple[int, ...]
    layer_volumes: tuple[int, ...]
    remainder_volume: int
    aircraft_surfaces: tuple[int, ...]
    expected_increments_m: tuple[float, ...]


def _prepare_near_wall_topology(
    *,
    fluid_volume: int,
    aircraft_surfaces: Sequence[int],
    farfield_surfaces: Sequence[int],
    strategy: MeshingStrategy,
) -> _LayerTopology:
    """Build a conformal layer/remainder partition with official Gmsh APIs."""

    gmsh.model.mesh.generate(2)
    source_face_count = _element_count_on_entities(2, aircraft_surfaces)
    if source_face_count <= 0:
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")

    increments = tuple(
        strategy.near_wall_first_height_m * strategy.near_wall_growth_ratio**index
        for index in range(strategy.near_wall_layer_count)
    )
    cumulative: list[float] = []
    height = 0.0
    for increment in increments:
        height += increment
        cumulative.append(height)
    if not math.isclose(
        height,
        strategy.near_wall_total_thickness_m,
        rel_tol=1.0e-12,
        abs_tol=1.0e-14,
    ):
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")

    oriented_boundary = gmsh.model.getBoundary(
        [(3, fluid_volume)], combined=True, oriented=True, recursive=False
    )
    farfield_set = set(farfield_surfaces)
    signed_farfield = tuple(
        signed_tag
        for dimension, signed_tag in oriented_boundary
        if dimension == 2 and abs(signed_tag) in farfield_set
    )
    if len(signed_farfield) != len(farfield_set):
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")

    extrusion = gmsh.model.geo.extrudeBoundaryLayer(
        [(2, tag) for tag in aircraft_surfaces],
        [1] * strategy.near_wall_layer_count,
        cumulative,
        True,
    )
    gmsh.model.geo.synchronize()
    layer_volumes = tuple(sorted({tag for dimension, tag in extrusion if dimension == 3}))
    if not layer_volumes:
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")

    combined_layer_boundary = gmsh.model.getBoundary(
        [(3, tag) for tag in layer_volumes],
        combined=True,
        oriented=True,
        recursive=False,
    )
    aircraft_set = set(aircraft_surfaces)
    signed_layer_tops = tuple(
        signed_tag
        for dimension, signed_tag in combined_layer_boundary
        if dimension == 2 and abs(signed_tag) not in aircraft_set
    )
    if not signed_layer_tops:
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")

    # The original OCC fluid volume would overlap the outward layer volumes.
    # Remove only that volume, retain its farfield surfaces, and reconstruct the
    # tetrahedral remainder against the layer-top surfaces in the built-in kernel.
    gmsh.model.occ.remove([(3, fluid_volume)], recursive=False)
    gmsh.model.occ.synchronize()
    surface_loop = gmsh.model.geo.addSurfaceLoop(
        [*signed_farfield, *(-tag for tag in signed_layer_tops)]
    )
    remainder_volume = gmsh.model.geo.addVolume([surface_loop])
    gmsh.model.geo.synchronize()
    fluid_volumes = (*layer_volumes, remainder_volume)
    if len(set(fluid_volumes)) != len(fluid_volumes):
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    return _LayerTopology(
        fluid_volumes=fluid_volumes,
        layer_volumes=layer_volumes,
        remainder_volume=remainder_volume,
        aircraft_surfaces=tuple(aircraft_surfaces),
        expected_increments_m=increments,
    )


def _validate_near_wall_mesh(
    topology: _LayerTopology, strategy: MeshingStrategy
) -> NearWallLayerEvidence:
    """Measure layer topology, spacing and signed cell evidence from Gmsh."""

    node_tags, coordinates, _parameters = gmsh.model.mesh.getNodes()
    node_coordinates = {
        int(node_tags[index]): (
            float(coordinates[3 * index]),
            float(coordinates[3 * index + 1]),
            float(coordinates[3 * index + 2]),
        )
        for index in range(len(node_tags))
    }
    layer_element_count = 0
    vertical_lengths: list[float] = []
    jacobians: list[float] = []
    volumes: list[float] = []
    for volume_tag in topology.layer_volumes:
        element_types, element_tag_groups, element_node_groups = gmsh.model.mesh.getElements(
            3, volume_tag
        )
        for element_type, element_tags, element_nodes in zip(
            element_types, element_tag_groups, element_node_groups, strict=True
        ):
            name, _dimension, _order, node_count, _local, _primary = (
                gmsh.model.mesh.getElementProperties(int(element_type))
            )
            if name.startswith("Prism"):
                vertical_pairs = ((0, 3), (1, 4), (2, 5))
            elif name.startswith("Hexahedron"):
                vertical_pairs = ((0, 4), (1, 5), (2, 6), (3, 7))
            else:
                raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
            typed_tags = [int(tag) for tag in element_tags]
            layer_element_count += len(typed_tags)
            jacobians.extend(
                float(value)
                for value in gmsh.model.mesh.getElementQualities(
                    typed_tags, "minDetJac"
                )
            )
            volumes.extend(
                float(value)
                for value in gmsh.model.mesh.getElementQualities(typed_tags, "volume")
            )
            connectivity = [int(tag) for tag in element_nodes]
            for offset in range(0, len(connectivity), node_count):
                element = connectivity[offset : offset + node_count]
                for first, second in vertical_pairs:
                    vertical_lengths.append(
                        math.dist(
                            node_coordinates[element[first]],
                            node_coordinates[element[second]],
                        )
                    )

    source_face_count = _element_count_on_entities(2, topology.aircraft_surfaces)
    expected_elements = source_face_count * strategy.near_wall_layer_count
    if layer_element_count != expected_elements or not vertical_lengths:
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    measured_groups: list[list[float]] = [
        [] for _increment in topology.expected_increments_m
    ]
    for measured in vertical_lengths:
        differences = [
            abs(measured - expected) for expected in topology.expected_increments_m
        ]
        closest = min(range(len(differences)), key=differences.__getitem__)
        tolerance = max(1.0e-10, topology.expected_increments_m[closest] * 1.0e-7)
        if differences[closest] > tolerance:
            raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
        measured_groups[closest].append(measured)
    if any(not group for group in measured_groups):
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    measured_increments = tuple(math.fsum(group) / len(group) for group in measured_groups)
    measured_growth = math.fsum(
        measured_increments[index + 1] / measured_increments[index]
        for index in range(len(measured_increments) - 1)
    ) / (len(measured_increments) - 1)
    measured_total = math.fsum(measured_increments)
    if not (
        math.isclose(
            measured_increments[0],
            strategy.near_wall_first_height_m,
            rel_tol=1.0e-7,
            abs_tol=1.0e-10,
        )
        and math.isclose(
            measured_growth,
            strategy.near_wall_growth_ratio,
            rel_tol=1.0e-7,
            abs_tol=1.0e-10,
        )
        and math.isclose(
            measured_total,
            strategy.near_wall_total_thickness_m,
            rel_tol=1.0e-7,
            abs_tol=1.0e-10,
        )
    ):
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    if not jacobians or not volumes:
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    negative_jacobians = sum(value <= 0.0 for value in jacobians)
    negative_volumes = sum(value <= 0.0 for value in volumes)
    if negative_jacobians or negative_volumes:
        raise MeshingError("NEAR_WALL_LAYER_NOT_VALIDATED")
    return NearWallLayerEvidence(
        api_path=_NEAR_WALL_API_PATH,
        gmsh_version=gmsh.__version__,
        source_face_count=source_face_count,
        layer_element_count=layer_element_count,
        validated_layer_count=len(measured_increments),
        measured_first_height_m=measured_increments[0],
        measured_growth_ratio=measured_growth,
        measured_total_thickness_m=measured_total,
        minimum_jacobian=min(jacobians),
        minimum_volume=min(volumes),
        negative_jacobian_count=negative_jacobians,
        negative_volume_count=negative_volumes,
    )


def _create_physical_groups(
    fluid_volumes: Sequence[int],
    aircraft_surfaces: Sequence[int],
    farfield_surfaces: Sequence[int],
) -> tuple[PhysicalGroupSummary, ...]:
    if set(aircraft_surfaces) & set(farfield_surfaces):
        raise MeshingError("BOUNDARY_GROUPS_OVERLAP")
    groups = (
        ("fluid", 3, tuple(fluid_volumes)),
        ("aircraft", 2, tuple(aircraft_surfaces)),
        ("farfield", 2, tuple(farfield_surfaces)),
    )
    for name, dimension, entity_tags in groups:
        if not entity_tags:
            raise MeshingError("PHYSICAL_GROUP_EMPTY")
        physical_tag = gmsh.model.addPhysicalGroup(dimension, list(entity_tags))
        gmsh.model.setPhysicalName(dimension, physical_tag, name)
    return _summarize_physical_groups(
        fluid_volumes, aircraft_surfaces, farfield_surfaces
    )


def _summarize_physical_groups(
    fluid_volumes: Sequence[int],
    aircraft_surfaces: Sequence[int],
    farfield_surfaces: Sequence[int],
) -> tuple[PhysicalGroupSummary, ...]:
    groups = (
        ("fluid", 3, tuple(fluid_volumes)),
        ("aircraft", 2, tuple(aircraft_surfaces)),
        ("farfield", 2, tuple(farfield_surfaces)),
    )
    return tuple(
        PhysicalGroupSummary(
            name=name,
            dimension=dimension,
            entity_count=len(entity_tags),
            bounding_boxes_m=tuple(
                _bounds_for_entity(dimension, entity_tag) for entity_tag in entity_tags
            ),
        )
        for name, dimension, entity_tags in groups
    )


def _enforce_generated_resources(strategy: MeshingStrategy) -> None:
    """Gate generated counts before quality, centroid, or face materialization."""

    node_tags, _coordinates, _parameters = gmsh.model.mesh.getNodes()
    _types, element_tag_groups, _node_groups = gmsh.model.mesh.getElements(3)
    node_count = len(node_tags)
    cell_count = sum(len(tags) for tags in element_tag_groups)
    enforce_resource_limits(
        node_count=node_count,
        cell_count=cell_count,
        estimated_memory_bytes=estimate_mesh_memory_bytes(
            node_count=node_count, cell_count=cell_count
        ),
        strategy=strategy,
    )


def _validate_whole_mesh_cells() -> WholeMeshValidityEvidence:
    """Use Gmsh signed metrics to prove every hybrid 3D cell is valid."""

    _types, element_tag_groups, _node_groups = gmsh.model.mesh.getElements(3)
    jacobians: list[float] = []
    volumes: list[float] = []
    cell_count = 0
    for tags in element_tag_groups:
        typed_tags = [int(tag) for tag in tags]
        cell_count += len(typed_tags)
        jacobians.extend(
            float(value)
            for value in gmsh.model.mesh.getElementQualities(
                typed_tags, "minDetJac"
            )
        )
        volumes.extend(
            float(value)
            for value in gmsh.model.mesh.getElementQualities(typed_tags, "volume")
        )
    if (
        cell_count <= 0
        or len(jacobians) != cell_count
        or len(volumes) != cell_count
    ):
        raise MeshingError("MESH_HAS_NO_VOLUME_ELEMENTS")
    non_finite_jacobians = sum(not math.isfinite(value) for value in jacobians)
    non_finite_volumes = sum(not math.isfinite(value) for value in volumes)
    non_positive_jacobians = sum(
        math.isfinite(value) and value <= 0.0 for value in jacobians
    )
    non_positive_volumes = sum(
        math.isfinite(value) and value <= 0.0 for value in volumes
    )
    if (
        non_finite_jacobians
        or non_finite_volumes
        or non_positive_jacobians
        or non_positive_volumes
    ):
        raise MeshingError("NEGATIVE_ELEMENT_QUALITY")
    return WholeMeshValidityEvidence(
        cell_count=cell_count,
        minimum_jacobian=min(jacobians),
        minimum_volume=min(volumes),
        non_finite_jacobian_count=non_finite_jacobians,
        non_finite_volume_count=non_finite_volumes,
        non_positive_jacobian_count=non_positive_jacobians,
        non_positive_volume_count=non_positive_volumes,
    )


def _validate_face_incidence(
    topology: _LayerTopology | None,
    strategy: MeshingStrategy,
) -> FaceIncidenceEvidence:
    """Prove complete external marking and conformal internal face sharing."""

    gmsh.model.mesh.createFaces()
    volume_entities = tuple(tag for _dimension, tag in gmsh.model.getEntities(3))
    volume_faces = _volume_face_occurrences(volume_entities)
    external_faces = {tag for tag, count in volume_faces.items() if count == 1}
    internal_faces = {tag for tag, count in volume_faces.items() if count == 2}
    nonconformal_faces = {
        tag for tag, count in volume_faces.items() if count not in (1, 2)
    }

    aircraft_entities = _physical_entities_named("aircraft", 2)
    farfield_entities = _physical_entities_named("farfield", 2)
    aircraft_face_list = _surface_face_tags(aircraft_entities)
    farfield_face_list = _surface_face_tags(farfield_entities)
    aircraft_faces = set(aircraft_face_list)
    farfield_faces = set(farfield_face_list)
    marker_occurrences: Counter[int] = Counter(aircraft_face_list)
    marker_occurrences.update(farfield_face_list)
    marked_faces = set(marker_occurrences)
    unmarked_external = external_faces - marked_faces
    multiply_marked_external = {
        tag
        for tag in external_faces
        if marker_occurrences.get(tag, 0) > 1
    }
    tagged_internal = marked_faces & internal_faces
    orphan_markers = marked_faces - external_faces - internal_faces

    layer_interface_faces: set[int] = set()
    if topology is not None:
        layer_faces = set(_volume_face_occurrences(topology.layer_volumes))
        remainder_faces = set(
            _volume_face_occurrences((topology.remainder_volume,))
        )
        layer_interface_faces = layer_faces & remainder_faces
        if any(volume_faces.get(tag) != 2 for tag in layer_interface_faces):
            nonconformal_faces.update(layer_interface_faces)

    evidence = FaceIncidenceEvidence(
        external_face_count=len(external_faces),
        internal_face_count=len(internal_faces),
        aircraft_face_count=len(aircraft_faces),
        farfield_face_count=len(farfield_faces),
        unmarked_external_face_count=len(unmarked_external),
        multiply_marked_external_face_count=len(multiply_marked_external),
        tagged_internal_face_count=len(tagged_internal),
        nonconformal_face_count=len(nonconformal_faces | orphan_markers),
        layer_interface_face_count=len(layer_interface_faces),
    )
    if (
        aircraft_faces & farfield_faces
        or evidence.unmarked_external_face_count
        or evidence.multiply_marked_external_face_count
        or evidence.tagged_internal_face_count
        or evidence.nonconformal_face_count
        or marked_faces != external_faces
        or (
            strategy.near_wall_layers_required
            and evidence.layer_interface_face_count <= 0
        )
    ):
        raise MeshingError("MESH_BOUNDARY_INCIDENCE_INVALID")
    return evidence


def _physical_entities_named(name: str, dimension: int) -> tuple[int, ...]:
    matches = [
        physical_tag
        for group_dimension, physical_tag in gmsh.model.getPhysicalGroups(dimension)
        if group_dimension == dimension
        and gmsh.model.getPhysicalName(group_dimension, physical_tag) == name
    ]
    if len(matches) != 1:
        raise MeshingError("MESH_BOUNDARY_INCIDENCE_INVALID")
    return tuple(
        int(tag)
        for tag in gmsh.model.getEntitiesForPhysicalGroup(dimension, matches[0])
    )


def _surface_face_tags(surface_entities: Sequence[int]) -> list[int]:
    faces: list[int] = []
    for surface_tag in surface_entities:
        element_types, _element_tags, node_groups = gmsh.model.mesh.getElements(
            2, surface_tag
        )
        for element_type, nodes in zip(element_types, node_groups, strict=True):
            (
                _name,
                _dimension,
                _order,
                node_count,
                _local,
                primary_node_count,
            ) = gmsh.model.mesh.getElementProperties(int(element_type))
            if primary_node_count not in (3, 4):
                raise MeshingError("MESH_BOUNDARY_INCIDENCE_INVALID")
            connectivity = [int(tag) for tag in nodes]
            primary_connectivity = [
                connectivity[offset + index]
                for offset in range(0, len(connectivity), node_count)
                for index in range(primary_node_count)
            ]
            face_tags, _orientations = gmsh.model.mesh.getFaces(
                primary_node_count, primary_connectivity
            )
            faces.extend(int(tag) for tag in face_tags if int(tag) > 0)
    return faces


def _volume_face_occurrences(volume_entities: Sequence[int]) -> Counter[int]:
    occurrences: Counter[int] = Counter()
    for volume_tag in volume_entities:
        element_types = gmsh.model.mesh.getElementTypes(3, volume_tag)
        for element_type in element_types:
            for face_type in (3, 4):
                face_nodes = gmsh.model.mesh.getElementFaceNodes(
                    int(element_type), face_type, volume_tag, True
                )
                if len(face_nodes) == 0:
                    continue
                face_tags, _orientations = gmsh.model.mesh.getFaces(
                    face_type, face_nodes
                )
                occurrences.update(
                    int(tag) for tag in face_tags if int(tag) > 0
                )
    return occurrences


def _enforce_predicted_resources(
    domain: ExternalDomain, strategy: MeshingStrategy
) -> None:
    """Apply a conservative region/layer-aware upper-bound estimate."""

    outer_volume = math.prod(domain.outer_bounds_m.dimensions_m)
    aircraft = domain.aircraft_bounds_m
    outer = domain.outer_bounds_m
    refinement_distance = strategy.aircraft_refinement_distance_max_m
    refinement_dimensions = tuple(
        max(
            0.0,
            min(outer.maximum_m[axis], aircraft.maximum_m[axis] + refinement_distance)
            - max(outer.minimum_m[axis], aircraft.minimum_m[axis] - refinement_distance),
        )
        for axis in range(3)
    )
    refinement_volume = math.prod(refinement_dimensions)
    wake_dimensions = (
        min(
            4.0 * domain.reference_length_m,
            outer.maximum_m[0] - aircraft.maximum_m[0],
        ),
        min(
            aircraft.dimensions_m[1] + 2.0 * domain.reference_length_m,
            outer.dimensions_m[1],
        ),
        min(
            aircraft.dimensions_m[2] + 2.0 * domain.reference_length_m,
            outer.dimensions_m[2],
        ),
    )
    wake_volume = math.prod(max(0.0, value) for value in wake_dimensions)
    aircraft_dimensions = aircraft.dimensions_m
    aircraft_box_area = 2.0 * (
        aircraft_dimensions[0] * aircraft_dimensions[1]
        + aircraft_dimensions[0] * aircraft_dimensions[2]
        + aircraft_dimensions[1] * aircraft_dimensions[2]
    )

    farfield_cells = 6.0 * outer_volume / strategy.farfield_size_m**3
    refinement_cells = (
        6.0 * refinement_volume / strategy.aircraft_size_min_m**3
    )
    wake_cells = 6.0 * wake_volume / strategy.wake_size_m**3
    layer_cells = (
        2.0
        * aircraft_box_area
        / strategy.aircraft_size_min_m**2
        * strategy.near_wall_layer_count
    )
    predicted_cells = max(
        1,
        math.ceil(
            1.5
            * (farfield_cells + refinement_cells + wake_cells + layer_cells)
        ),
    )
    # A connected hybrid volume mesh has substantially fewer nodes than cells;
    # using one node per conservatively overestimated cell is deliberately
    # safer than the previous cells/5 underestimate while keeping validated
    # Fine meshes inside the configured default ceiling.
    predicted_nodes = predicted_cells
    enforce_resource_limits(
        node_count=predicted_nodes,
        cell_count=predicted_cells,
        estimated_memory_bytes=estimate_mesh_memory_bytes(
            node_count=predicted_nodes, cell_count=predicted_cells
        ),
        strategy=strategy,
    )


def _configure_preview_mesh_fields(
    *,
    aircraft_surfaces: Sequence[int],
    domain: ExternalDomain,
    strategy: MeshingStrategy,
) -> None:
    # Keep the imported CAD boundary sufficiently resolved even when the user
    # requests a coarse volume mesh. This uses Gmsh's official Restrict field:
    # it does not alter OCC geometry and avoids the invalid BSpline triangles
    # reproduced on example_model.STEP with a 0.25 m boundary size.
    surface_resolution_m = strategy.aircraft_size_min_m
    if not strategy.near_wall_layers_required:
        surface_resolution_m = min(
            surface_resolution_m,
            domain.aircraft_bounds_m.diagonal_m / 100.0,
        )
    gmsh.option.setNumber("Mesh.MeshSizeMin", surface_resolution_m)
    gmsh.option.setNumber("Mesh.MeshSizeMax", strategy.farfield_size_m)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)
    gmsh.option.setNumber("Mesh.MaxNumThreads3D", 1)
    gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
    gmsh.option.setNumber("Mesh.Binary", 1)
    gmsh.option.setNumber("Mesh.SaveAll", 0)
    aircraft_points = tuple(
        sorted(
            {
                abs(tag)
                for dimension, tag in gmsh.model.getBoundary(
                    [(2, tag) for tag in aircraft_surfaces],
                    combined=False,
                    oriented=False,
                    recursive=True,
                )
                if dimension == 0
            }
        )
    )
    if aircraft_points:
        gmsh.model.mesh.setSize(
            [(0, tag) for tag in aircraft_points], surface_resolution_m
        )

    distance = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(distance, "SurfacesList", aircraft_surfaces)
    gmsh.model.mesh.field.setNumber(distance, "Sampling", 100)

    threshold = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
    gmsh.model.mesh.field.setNumber(threshold, "SizeMin", strategy.aircraft_size_min_m)
    gmsh.model.mesh.field.setNumber(threshold, "SizeMax", strategy.aircraft_size_max_m)
    gmsh.model.mesh.field.setNumber(
        threshold, "DistMin", strategy.aircraft_refinement_distance_min_m
    )
    gmsh.model.mesh.field.setNumber(
        threshold, "DistMax", strategy.aircraft_refinement_distance_max_m
    )

    aircraft = domain.aircraft_bounds_m
    wake = gmsh.model.mesh.field.add("Box")
    gmsh.model.mesh.field.setNumber(wake, "VIn", strategy.wake_size_m)
    gmsh.model.mesh.field.setNumber(wake, "VOut", strategy.farfield_size_m)
    gmsh.model.mesh.field.setNumber(wake, "XMin", aircraft.maximum_m[0])
    gmsh.model.mesh.field.setNumber(
        wake, "XMax", aircraft.maximum_m[0] + 4.0 * domain.reference_length_m
    )
    gmsh.model.mesh.field.setNumber(
        wake, "YMin", aircraft.minimum_m[1] - domain.reference_length_m
    )
    gmsh.model.mesh.field.setNumber(
        wake, "YMax", aircraft.maximum_m[1] + domain.reference_length_m
    )
    gmsh.model.mesh.field.setNumber(
        wake, "ZMin", aircraft.minimum_m[2] - domain.reference_length_m
    )
    gmsh.model.mesh.field.setNumber(
        wake, "ZMax", aircraft.maximum_m[2] + domain.reference_length_m
    )

    fields = [threshold, wake]
    if surface_resolution_m < strategy.aircraft_size_min_m:
        constant = gmsh.model.mesh.field.add("MathEval")
        gmsh.model.mesh.field.setString(constant, "F", f"{surface_resolution_m:.17g}")
        restricted = gmsh.model.mesh.field.add("Restrict")
        gmsh.model.mesh.field.setNumber(restricted, "InField", constant)
        gmsh.model.mesh.field.setNumbers(
            restricted, "SurfacesList", aircraft_surfaces
        )
        fields.append(restricted)

    combined = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(combined, "FieldsList", fields)
    gmsh.model.mesh.field.setAsBackgroundMesh(combined)


def _quality_report(
    *,
    strategy: MeshingStrategy,
    aircraft_surfaces: Sequence[int],
    farfield_surfaces: Sequence[int],
    summaries: Sequence[PhysicalGroupSummary],
    near_wall_evidence: NearWallLayerEvidence | None,
    whole_mesh_validity: WholeMeshValidityEvidence,
    face_incidence: FaceIncidenceEvidence,
):
    element_types, element_tag_groups, node_groups = gmsh.model.mesh.getElements(3)
    referenced_node_tags = {
        int(node_tag) for node_group in node_groups for node_tag in node_group
    }
    element_type_counts: dict[str, int] = {}
    element_tags: list[int] = []
    qualities: list[float] = []
    centroids: list[Vector3] = []
    for element_type, tags in zip(element_types, element_tag_groups, strict=True):
        name, _dimension, _order, _nodes, _local, _primary = (
            gmsh.model.mesh.getElementProperties(int(element_type))
        )
        typed_tags = [int(tag) for tag in tags]
        element_type_counts[name] = element_type_counts.get(name, 0) + len(typed_tags)
        element_tags.extend(typed_tags)
        qualities.extend(
            float(value)
            for value in gmsh.model.mesh.getElementQualities(typed_tags, "minSICN")
        )
        coordinates = gmsh.model.mesh.getBarycenters(
            int(element_type), -1, False, True
        )
        centroids.extend(
            (
                float(coordinates[index]),
                float(coordinates[index + 1]),
                float(coordinates[index + 2]),
            )
            for index in range(0, len(coordinates), 3)
        )
    boundary_face_counts = {
        "aircraft": _element_count_on_entities(2, aircraft_surfaces),
        "farfield": _element_count_on_entities(2, farfield_surfaces),
    }
    return build_quality_report(
        node_count=len(referenced_node_tags),
        element_type_counts=element_type_counts,
        qualities=qualities,
        element_tags=element_tags,
        centroids=centroids,
        boundary_face_counts=boundary_face_counts,
        physical_group_counts={summary.name: summary.entity_count for summary in summaries},
        strategy=strategy,
        non_manifold_face_count=face_incidence.nonconformal_face_count,
        near_wall_evidence=near_wall_evidence,
        whole_mesh_validity=whole_mesh_validity,
        face_incidence=face_incidence,
    )


def _element_count_on_entities(dimension: int, entity_tags: Sequence[int]) -> int:
    count = 0
    for entity_tag in entity_tags:
        _types, tag_groups, _nodes = gmsh.model.mesh.getElements(dimension, entity_tag)
        count += sum(len(tags) for tags in tag_groups)
    return count


def _write_and_verify_artifacts(
    *,
    output_directory: Path,
    su2_validator_path: Path,
    domain: ExternalDomain,
    strategy: MeshingStrategy,
    summaries: tuple[PhysicalGroupSummary, ...],
    quality,
) -> MeshArtifacts:
    filenames = {
        "msh": "external_flow.msh",
        "su2": "external_flow.su2",
        "vtu": "external_flow.vtu",
        "mapping": "physical_groups.json",
        "quality": "mesh_quality.json",
    }
    try:
        publication_directory = _validated_publication_directory(
            output_directory, tuple(filenames.values())
        )
        with TemporaryDirectory(
            prefix=f".{publication_directory.name}.stage-",
            dir=publication_directory.parent,
        ) as temporary:
            staging_directory = Path(temporary)
            paths = {key: staging_directory / value for key, value in filenames.items()}
            gmsh.write(str(paths["msh"]))
            gmsh.write(str(paths["su2"]))
            _verify_msh_round_trip(paths["msh"], summaries)
            _verify_su2_round_trip(
                paths["su2"], quality, su2_validator_path
            )
            visualization = meshio.read(paths["msh"])
            expected_cell_counts = _meshio_cell_counts(visualization)
            # VTU has no cell-set concept. meshio's automatic conversion is not
            # valid for sparse Gmsh entity blocks, while points, cells and cell
            # data remain directly supported visualization content.
            visualization.cell_sets = {}
            meshio.write(paths["vtu"], visualization, file_format="vtu", binary=True)
            restored_visualization = meshio.read(paths["vtu"])
            if (
                len(restored_visualization.points) != quality.node_count
                or _meshio_cell_counts(restored_visualization)
                != expected_cell_counts
            ):
                raise MeshingError("MESH_ARTIFACT_ROUNDTRIP_FAILED")
            mapping = {
                "coordinate_mapping": {
                    "x": "-z_original",
                    "y": "x_original",
                    "z": "y_original",
                },
                "domain": domain.to_dict(),
                "strategy": strategy.to_dict(),
                "physical_groups": [summary.to_dict() for summary in summaries],
            }
            paths["mapping"].write_text(
                json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            paths["quality"].write_text(
                json.dumps(
                    quality.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            _verify_staging_containment(staging_directory, tuple(paths.values()))
            _publish_complete_set(staging_directory, publication_directory)
            final_paths = {
                key: publication_directory / value
                for key, value in filenames.items()
            }
    except MeshingError:
        raise
    except Exception as error:
        raise MeshingError("MESH_ARTIFACT_WRITE_FAILED") from error
    return MeshArtifacts(
        msh_path=final_paths["msh"],
        su2_path=final_paths["su2"],
        vtu_path=final_paths["vtu"],
        mapping_json_path=final_paths["mapping"],
        quality_json_path=final_paths["quality"],
        domain=domain,
        strategy=strategy,
        physical_groups=summaries,
        quality=quality,
    )


def _meshio_cell_counts(mesh) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for block in mesh.cells:
        counts[str(block.type)] += len(block.data)
    return dict(sorted(counts.items()))


def _verify_su2_round_trip(
    su2_path: Path, quality, su2_validator_path: Path
) -> None:
    """Reopen Gmsh SU2 through official SU2 and verify semantic counts."""

    verification_directory = su2_path.parent / ".su2-reader"
    verification_directory.mkdir()
    config_path = verification_directory / "verify.cfg"
    config_path.write_text(
        "\n".join(
            (
                "SOLVER= EULER",
                f"MESH_FILENAME= ../{su2_path.name}",
                "MESH_FORMAT= SU2",
                "MATH_PROBLEM= DIRECT",
                "RESTART_SOL= NO",
                "MACH_NUMBER= 0.1",
                "AOA= 0.0",
                "FREESTREAM_PRESSURE= 101325.0",
                "FREESTREAM_TEMPERATURE= 288.15",
                "REF_DIMENSIONALIZATION= DIMENSIONAL",
                "MARKER_EULER= ( aircraft )",
                "MARKER_FAR= ( farfield )",
                "MARKER_PLOTTING= ( aircraft, farfield )",
                "MARKER_MONITORING= ( aircraft )",
                "ITER= 0",
                "MGLEVEL= 0",
                "CONV_NUM_METHOD_FLOW= ROE",
                "TIME_DISCRE_FLOW= EULER_EXPLICIT",
                "NUM_METHOD_GRAD= GREEN_GAUSS",
                "CFL_NUMBER= 1.0",
                "SCREEN_OUTPUT= ( INNER_ITER, RMS_DENSITY )",
                "HISTORY_OUTPUT= ( ITER, RMS_RES )",
                "OUTPUT_FILES= ( RESTART )",
                "",
            )
        ),
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [str(su2_validator_path), "-t", "1", config_path.name],
            cwd=verification_directory,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise MeshingError("MESH_ARTIFACT_ROUNDTRIP_FAILED")
        output = result.stdout
        nodes = re.search(r"(?m)^\s*(\d+) grid points\.\s*$", output)
        cells = re.search(r"(?m)^\s*(\d+) volume elements\.\s*$", output)
        marker_matches = re.findall(
            r"(?m)^\s*(\d+) boundary elements in index \d+ "
            r"\(Marker = ([^)]+)\)\.\s*$",
            output,
        )
        markers = {
            name.strip(): int(count) for count, name in marker_matches
        }
        expected_markers = dict(quality.boundary_face_counts)
        if (
            nodes is None
            or cells is None
            or int(nodes.group(1)) != quality.node_count
            or int(cells.group(1)) != quality.cell_count
            or markers != expected_markers
        ):
            raise MeshingError("MESH_ARTIFACT_ROUNDTRIP_FAILED")
    finally:
        shutil.rmtree(verification_directory, ignore_errors=True)


def _validated_publication_directory(
    requested: Path, filenames: Sequence[str]
) -> Path:
    requested = Path(requested)
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    if _is_redirecting_path(requested):
        raise MeshingError("MESH_ARTIFACT_WRITE_FAILED")
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = requested.parent.resolve(strict=True)
    publication = parent / requested.name
    if publication.exists():
        if not publication.is_dir() or _is_redirecting_path(publication):
            raise MeshingError("MESH_ARTIFACT_WRITE_FAILED")
        for child in publication.iterdir():
            if _is_redirecting_path(child):
                raise MeshingError("MESH_ARTIFACT_WRITE_FAILED")
    for filename in filenames:
        destination = publication / filename
        if destination.exists() and _is_redirecting_path(destination):
            raise MeshingError("MESH_ARTIFACT_WRITE_FAILED")
    return publication


def _is_redirecting_path(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        return path.is_file() and path.stat().st_nlink > 1
    except FileNotFoundError:
        return False


def _verify_staging_containment(
    staging_directory: Path, artifact_paths: Sequence[Path]
) -> None:
    staging_root = staging_directory.resolve(strict=True)
    for artifact_path in artifact_paths:
        if (
            artifact_path.is_symlink()
            or not artifact_path.is_file()
            or artifact_path.resolve(strict=True).parent != staging_root
        ):
            raise MeshingError("MESH_ARTIFACT_WRITE_FAILED")


def _publish_complete_set(staging_directory: Path, output_directory: Path) -> None:
    backup_directory = output_directory.parent / (
        f".{output_directory.name}.backup-{uuid4().hex}"
    )
    had_previous = output_directory.exists()
    if had_previous:
        output_directory.replace(backup_directory)
    try:
        staging_directory.replace(output_directory)
    except Exception:
        if had_previous and backup_directory.exists():
            backup_directory.replace(output_directory)
        raise
    if had_previous:
        shutil.rmtree(backup_directory)


def _verify_msh_round_trip(
    msh_path: Path, expected: Sequence[PhysicalGroupSummary]
) -> None:
    original_model = gmsh.model.getCurrent()
    verification_model = f"phoenix-msh-roundtrip-{uuid4().hex}"
    try:
        gmsh.model.add(verification_model)
        gmsh.model.setCurrent(verification_model)
        gmsh.merge(str(msh_path))
        actual: dict[str, tuple[int, int]] = {}
        for dimension, physical_tag in gmsh.model.getPhysicalGroups():
            name = gmsh.model.getPhysicalName(dimension, physical_tag)
            actual[name] = (
                dimension,
                len(gmsh.model.getEntitiesForPhysicalGroup(dimension, physical_tag)),
            )
        durable_expected = {
            summary.name: (summary.dimension, summary.entity_count) for summary in expected
        }
        if actual != durable_expected:
            raise MeshingError("MESH_ARTIFACT_ROUNDTRIP_FAILED")
    finally:
        if gmsh.isInitialized() and verification_model in gmsh.model.list():
            gmsh.model.setCurrent(verification_model)
            gmsh.model.remove()
        if gmsh.isInitialized() and original_model in gmsh.model.list():
            gmsh.model.setCurrent(original_model)


def _bounds_for_entity(dimension: int, entity_tag: int) -> BoundingBox:
    bounds = gmsh.model.getBoundingBox(dimension, entity_tag)
    return BoundingBox(
        minimum_m=(float(bounds[0]), float(bounds[1]), float(bounds[2])),
        maximum_m=(float(bounds[3]), float(bounds[4]), float(bounds[5])),
    )


def _mapped_bounds(original: BoundingBox) -> BoundingBox:
    """Map axis-aligned bounds through (x, y, z) -> (-z, x, y)."""

    return BoundingBox(
        minimum_m=(
            -original.maximum_m[2],
            original.minimum_m[0],
            original.minimum_m[1],
        ),
        maximum_m=(
            -original.minimum_m[2],
            original.maximum_m[0],
            original.maximum_m[1],
        ),
    )


@contextmanager
def _meshing_model() -> Iterator[None]:
    """Own only this temporary model and restore a caller-owned Gmsh session."""

    with _GMSH_LOCK:
        owns_session = not bool(gmsh.isInitialized())
        previous_model = ""
        previous_target_unit = ""
        previous_numbers: dict[str, float] = {}
        model_name = f"phoenix-external-mesh-{uuid4().hex}"
        model_added = False
        try:
            if owns_session:
                gmsh.initialize(interruptible=False)
            previous_model = gmsh.model.getCurrent()
            previous_target_unit = gmsh.option.getString("Geometry.OCCTargetUnit")
            previous_numbers = {
                name: gmsh.option.getNumber(name) for name in _NUMBER_OPTIONS
            }
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setString("Geometry.OCCTargetUnit", _OCC_TARGET_UNIT)
            gmsh.model.add(model_name)
            model_added = True
            yield
        finally:
            if gmsh.isInitialized():
                try:
                    if model_added and model_name in gmsh.model.list():
                        gmsh.model.setCurrent(model_name)
                        gmsh.model.remove()
                finally:
                    try:
                        gmsh.option.setString(
                            "Geometry.OCCTargetUnit", previous_target_unit
                        )
                        for name, value in previous_numbers.items():
                            gmsh.option.setNumber(name, value)
                        if previous_model and previous_model in gmsh.model.list():
                            gmsh.model.setCurrent(previous_model)
                    finally:
                        if owns_session:
                            gmsh.finalize()
