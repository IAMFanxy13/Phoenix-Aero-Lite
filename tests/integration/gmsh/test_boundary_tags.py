"""Post-Boolean geometric boundary identity and MSH round-trip tests."""

from __future__ import annotations

from pathlib import Path

import gmsh
import pytest

from phoenix_aero_lite.meshing.gmsh_mesher import (
    _classify_fluid_boundaries,
    _create_physical_groups,
)
from phoenix_aero_lite.models.geometry import BoundingBox
from phoenix_aero_lite.models.mesh import MeshingError
from phoenix_aero_lite.models.parameters import MeshMode, MeshParameters


def test_aircraft_and_farfield_groups_are_disjoint_and_survive_msh_round_trip(
    tmp_path: Path, synthetic_step_factory, external_mesher
):
    step_path = synthetic_step_factory(tmp_path / "wing.step")
    artifacts = external_mesher().build_external_mesh(
        step_path,
        MeshParameters(MeshMode.PREVIEW, 1.0),
        tmp_path / "mesh",
    )
    summaries = {group.name: group for group in artifacts.physical_groups}

    assert summaries["fluid"].dimension == 3
    assert summaries["fluid"].entity_count == 1
    assert summaries["aircraft"].dimension == 2
    assert summaries["farfield"].dimension == 2
    assert set(summaries["aircraft"].bounding_boxes_m).isdisjoint(
        summaries["farfield"].bounding_boxes_m
    )

    gmsh.initialize()
    try:
        gmsh.open(str(artifacts.msh_path))
        round_trip = {}
        for dimension, physical_tag in gmsh.model.getPhysicalGroups():
            name = gmsh.model.getPhysicalName(dimension, physical_tag)
            round_trip[name] = (
                dimension,
                len(gmsh.model.getEntitiesForPhysicalGroup(dimension, physical_tag)),
            )
        assert round_trip == {
            name: (summary.dimension, summary.entity_count)
            for name, summary in summaries.items()
        }
    finally:
        gmsh.finalize()


def test_classifier_reports_lost_aircraft_boundary_on_an_uncut_outer_box():
    gmsh.initialize()
    try:
        gmsh.model.add("uncut-domain")
        volume_tag = gmsh.model.occ.addBox(-1.0, -1.0, -1.0, 2.0, 2.0, 2.0)
        gmsh.model.occ.synchronize()

        with pytest.raises(MeshingError) as error:
            _classify_fluid_boundaries(
                volume_tag,
                BoundingBox((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
            )

        assert error.value.issue.code == "AIRCRAFT_BOUNDARY_LOST"
    finally:
        gmsh.finalize()


def test_physical_group_creation_defends_against_overlapping_boundary_identity():
    gmsh.initialize()
    try:
        gmsh.model.add("overlapping-boundaries")
        volume_tag = gmsh.model.occ.addBox(-1.0, -1.0, -1.0, 2.0, 2.0, 2.0)
        gmsh.model.occ.synchronize()
        surface_tag = gmsh.model.getBoundary([(3, volume_tag)])[0][1]

        with pytest.raises(MeshingError) as error:
            _create_physical_groups(
                (volume_tag,),
                (surface_tag,),
                (surface_tag,),
            )

        assert error.value.issue.code == "BOUNDARY_GROUPS_OVERLAP"
    finally:
        gmsh.finalize()
