"""Exercise meshio's public Gmsh-to-VTU conversion APIs."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
from pathlib import Path

import meshio
import numpy as np


POINT_RTOL = 1.0e-12
POINT_ATOL = 1.0e-12


def prepare_mesh_for_export(mesh: meshio.Mesh) -> meshio.Mesh:
    """Copy a mesh and omit Gmsh's oriented CAD-adjacency metadata.

    ``gmsh:bounding_entities`` contains signed entity tags rather than cell
    indices, so meshio's generic cell-set conversion must not consume it.
    Physical cell sets are preserved.
    """
    prepared = copy.deepcopy(mesh)
    prepared.cell_sets.pop("gmsh:bounding_entities", None)
    return prepared


def write_vtu_conversion(mesh: meshio.Mesh, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "converted.vtu"
    prepared = prepare_mesh_for_export(mesh)
    groups = _physical_group_indices(prepared)
    for name, block_members in groups.items():
        masks = []
        for block, members in zip(prepared.cells, block_members, strict=True):
            mask = np.zeros(len(block.data), dtype=np.uint8)
            mask[list(members)] = 1
            masks.append(mask)
        prepared.cell_data[f"physical:{name}"] = masks
    prepared.cell_sets.clear()
    meshio.write(output, prepared)
    return output


def mesh_topology(mesh: meshio.Mesh) -> dict[str, object]:
    cell_counts = Counter()
    for block in mesh.cells:
        cell_counts[block.type] += len(block.data)
    return {
        "points": len(mesh.points),
        "cell_counts": dict(sorted(cell_counts.items())),
    }


def canonical_cells(
    mesh: meshio.Mesh,
) -> dict[str, tuple[tuple[int, ...], ...]]:
    """Return exact connectivity, independent of meshio cell-block partitioning."""
    cells: dict[str, list[tuple[int, ...]]] = {}
    for block in mesh.cells:
        by_type = cells.setdefault(block.type, [])
        by_type.extend(
            tuple(int(point) for point in np.asarray(connectivity).flat)
            for connectivity in block.data
        )
    return {cell_type: tuple(sorted(items)) for cell_type, items in sorted(cells.items())}


def _physical_group_indices(mesh: meshio.Mesh) -> dict[str, list[set[int]]]:
    groups: dict[str, list[set[int]]] = {}

    def blocks_for(name: str) -> list[set[int]]:
        return groups.setdefault(name, [set() for _ in mesh.cells])

    for name, cell_set_blocks in mesh.cell_sets.items():
        if name == "gmsh:bounding_entities":
            continue
        members = blocks_for(name)
        for block_index, indices in enumerate(cell_set_blocks):
            if indices is not None:
                members[block_index].update(int(index) for index in indices)

    gmsh_labels = mesh.cell_data.get("gmsh:physical")
    if gmsh_labels is not None:
        for name, tag_and_dimension in mesh.field_data.items():
            tag = int(tag_and_dimension[0])
            dimension = int(tag_and_dimension[1])
            members = blocks_for(name)
            for block_index, (block, labels) in enumerate(
                zip(mesh.cells, gmsh_labels, strict=True)
            ):
                if block.dim != dimension:
                    continue
                members[block_index].update(
                    int(index) for index in np.flatnonzero(np.asarray(labels) == tag)
                )

    for key, masks in mesh.cell_data.items():
        if not key.startswith("physical:"):
            continue
        members = blocks_for(key.removeprefix("physical:"))
        for block_index, mask in enumerate(masks):
            members[block_index].update(
                int(index) for index in np.flatnonzero(np.asarray(mask) != 0)
            )

    return groups


def physical_group_membership(
    mesh: meshio.Mesh,
) -> dict[str, tuple[tuple[str, tuple[int, ...]], ...]]:
    groups = _physical_group_indices(mesh)
    canonical: dict[str, tuple[tuple[str, tuple[int, ...]], ...]] = {}
    for name, block_members in sorted(groups.items()):
        cells: list[tuple[str, tuple[int, ...]]] = []
        for block, member_indices in zip(mesh.cells, block_members, strict=True):
            for index in member_indices:
                connectivity = tuple(
                    sorted(int(point) for point in np.asarray(block.data[index]).flat)
                )
                cells.append((block.type, connectivity))
        canonical[name] = tuple(sorted(cells))
    return canonical


def validate_mesh_roundtrip(source: meshio.Mesh, reread: meshio.Mesh) -> None:
    source_topology = mesh_topology(source)
    reread_topology = mesh_topology(reread)
    if source_topology["points"] != reread_topology["points"]:
        raise ValueError("point count changed during mesh conversion")
    if source_topology["cell_counts"] != reread_topology["cell_counts"]:
        raise ValueError("cell counts changed during mesh conversion")
    if canonical_cells(source) != canonical_cells(reread):
        raise ValueError("cell connectivity changed during mesh conversion")

    # Writers may round floating-point text, so coordinates use a documented,
    # deliberately tight absolute/relative tolerance instead of byte equality.
    if source.points.shape != reread.points.shape or not np.allclose(
        source.points,
        reread.points,
        rtol=POINT_RTOL,
        atol=POINT_ATOL,
        equal_nan=False,
    ):
        raise ValueError("point coordinates changed during mesh conversion")

    source_groups = physical_group_membership(source)
    reread_groups = physical_group_membership(reread)
    if source_groups != reread_groups:
        raise ValueError("physical group membership changed during mesh conversion")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    mesh = meshio.read(args.source)
    output = write_vtu_conversion(mesh, args.output_dir)
    reread = meshio.read(output)
    validate_mesh_roundtrip(mesh, reread)
    result = {
        "conversion": "Gmsh MSH to VTK VTU",
        "topology_preserved": True,
        "physical_group_membership_preserved": True,
        "source": str(args.source.resolve()),
        "source_topology": mesh_topology(mesh),
        "source_physical_groups": physical_group_membership(mesh),
        "output": {
            "path": str(output.resolve()),
            "bytes": output.stat().st_size,
            "topology": mesh_topology(reread),
            "physical_groups": physical_group_membership(reread),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
