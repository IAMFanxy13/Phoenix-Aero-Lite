import gmsh
import pytest

from phoenix_aero_lite.meshing.gmsh_mesher import _generate_volume_mesh_checked
from phoenix_aero_lite.models.mesh import MeshingError


def test_explicit_invalid_surface_warning_blocks_solver_mesh(monkeypatch):
    calls = []
    monkeypatch.setattr(gmsh.logger, "start", lambda: calls.append("start"))
    monkeypatch.setattr(gmsh.logger, "get", lambda: [
        "Warning: 10 elements remain invalid in surface 35"
    ])
    monkeypatch.setattr(gmsh.logger, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(gmsh.model.mesh, "generate", lambda dimension: calls.append(dimension))

    with pytest.raises(MeshingError) as error:
        _generate_volume_mesh_checked()

    assert error.value.issue.code == "MESH_INVALID_SURFACE_ELEMENTS"
    assert error.value.gmsh_messages == (
        "Warning: 10 elements remain invalid in surface 35",
    )
    assert calls == ["start", 3, "stop"]


def test_volume_mesh_without_explicit_invalid_warning_continues(monkeypatch):
    monkeypatch.setattr(gmsh.logger, "start", lambda: None)
    monkeypatch.setattr(gmsh.logger, "get", lambda: ["Info: volume mesh complete"])
    monkeypatch.setattr(gmsh.logger, "stop", lambda: None)
    monkeypatch.setattr(gmsh.model.mesh, "generate", lambda _dimension: None)

    _generate_volume_mesh_checked()
