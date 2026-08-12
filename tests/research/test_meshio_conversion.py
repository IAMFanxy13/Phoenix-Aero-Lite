from __future__ import annotations

import numpy as np
import meshio
import pytest

from scripts.research.validate_meshio_conversion import (
    physical_group_membership,
    prepare_mesh_for_export,
    validate_mesh_roundtrip,
    write_vtu_conversion,
)


def test_prepare_mesh_for_export_drops_only_gmsh_bounding_entities(tmp_path):
    mesh = meshio.Mesh(
        points=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        cells=[("line", np.array([[0, 1]]))],
        cell_sets={
            "gmsh:bounding_entities": [np.array([-1, 0])],
            "wall": [np.array([0])],
        },
    )

    prepared = prepare_mesh_for_export(mesh)
    assert "gmsh:bounding_entities" in mesh.cell_sets
    assert "gmsh:bounding_entities" not in prepared.cell_sets
    assert "wall" in prepared.cell_sets

    output = tmp_path / "prepared.vtu"
    meshio.write(output, prepared)

    reread = meshio.read(output)
    assert reread.cells[0].type == "line"
    assert "wall" in reread.cell_data


def test_write_vtu_conversion_returns_a_readable_mesh(tmp_path):
    mesh = meshio.Mesh(
        points=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        ),
        cells=[("triangle", np.array([[0, 1, 2]]))],
    )

    output = write_vtu_conversion(mesh, tmp_path)

    assert output.name == "converted.vtu"
    assert meshio.read(output).cells[0].type == "triangle"


def test_validate_mesh_roundtrip_rejects_dropped_cells():
    source = meshio.Mesh(
        points=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        ),
        cells=[("triangle", np.array([[0, 1, 2], [0, 2, 1]]))],
    )
    truncated = meshio.Mesh(
        points=source.points,
        cells=[("triangle", np.array([[0, 1, 2]]))],
    )

    with pytest.raises(ValueError, match="cell counts changed"):
        validate_mesh_roundtrip(source, truncated)


def test_validate_mesh_roundtrip_requires_physical_groups():
    source = meshio.Mesh(
        points=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        ),
        cells=[("triangle", np.array([[0, 1, 2]]))],
        cell_sets={"aircraft": [np.array([0])]},
    )
    without_groups = meshio.Mesh(points=source.points, cells=source.cells)

    with pytest.raises(ValueError, match="physical group membership changed"):
        validate_mesh_roundtrip(source, without_groups)


def test_validate_mesh_roundtrip_rejects_wrong_physical_group_membership():
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ]
    )
    cells = [("triangle", np.array([[0, 1, 2], [1, 3, 2]]))]
    source = meshio.Mesh(
        points=points,
        cells=cells,
        cell_sets={"aircraft": [np.array([0])]},
    )
    wrong_membership = meshio.Mesh(
        points=points,
        cells=cells,
        cell_sets={"aircraft": [np.array([1])]},
    )

    with pytest.raises(ValueError, match="physical group membership changed"):
        validate_mesh_roundtrip(source, wrong_membership)


def test_vtu_conversion_preserves_multiple_physical_group_memberships(tmp_path):
    mesh = meshio.Mesh(
        points=np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
            ]
        ),
        cells=[("triangle", np.array([[0, 1, 2], [1, 3, 2]]))],
        cell_sets={
            "aircraft": [np.array([1])],
            "farfield": [np.array([0])],
        },
    )

    output = write_vtu_conversion(mesh, tmp_path)
    reread = meshio.read(output)
    validate_mesh_roundtrip(mesh, reread)

    assert reread.cell_data["physical:aircraft"][0].tolist() == [0, 1]
    assert reread.cell_data["physical:farfield"][0].tolist() == [1, 0]


def test_gmsh_physical_tags_are_isolated_by_topological_dimension():
    mesh = meshio.Mesh(
        points=np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        ),
        cells=[
            ("line", np.array([[0, 1]])),
            ("triangle", np.array([[0, 1, 2]])),
        ],
        cell_data={
            "gmsh:physical": [np.array([7]), np.array([7])],
        },
        field_data={
            "edge": np.array([7, 1]),
            "surface": np.array([7, 2]),
        },
    )

    groups = physical_group_membership(mesh)

    assert groups["edge"] == (("line", (0, 1)),)
    assert groups["surface"] == (("triangle", (0, 1, 2)),)


def test_validate_mesh_roundtrip_rejects_changed_connectivity_with_same_counts():
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ]
    )
    source = meshio.Mesh(
        points=points,
        cells=[("triangle", np.array([[0, 1, 2], [1, 3, 2]]))],
    )
    changed = meshio.Mesh(
        points=points,
        cells=[("triangle", np.array([[0, 1, 3], [0, 3, 2]]))],
    )

    with pytest.raises(ValueError, match="cell connectivity changed"):
        validate_mesh_roundtrip(source, changed)


def test_validate_mesh_roundtrip_rejects_changed_point_coordinates():
    source = meshio.Mesh(
        points=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        ),
        cells=[("triangle", np.array([[0, 1, 2]]))],
    )
    moved = meshio.Mesh(
        points=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.01, 0.0]]
        ),
        cells=source.cells,
    )

    with pytest.raises(ValueError, match="point coordinates changed"):
        validate_mesh_roundtrip(source, moved)


def test_validate_mesh_roundtrip_ignores_cell_block_partitioning():
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ]
    )
    partitioned = meshio.Mesh(
        points=points,
        cells=[
            ("triangle", np.array([[0, 1, 2]])),
            ("triangle", np.array([[1, 3, 2]])),
        ],
    )
    merged = meshio.Mesh(
        points=points,
        cells=[("triangle", np.array([[0, 1, 2], [1, 3, 2]]))],
    )

    validate_mesh_roundtrip(partitioned, merged)
