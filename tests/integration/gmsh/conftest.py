"""Synthetic OpenCASCADE STEP fixtures for meshing integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import gmsh
import pytest

from phoenix_aero_lite.meshing.gmsh_mesher import GmshMesher


@pytest.fixture(scope="session")
def official_su2_validator_path() -> Path:
    """Load the ignored trusted path outside the mesher dependency boundary."""

    project_root = Path(__file__).resolve().parents[3]
    candidates = (
        project_root / "config" / "local_tools.json",
        project_root.parent.parent / "config" / "local_tools.json",
    )
    config_path = next((path for path in candidates if path.is_file()), None)
    if config_path is None:
        pytest.skip("trusted config/local_tools.json is unavailable")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    executable = Path(config["su2_cfd_executable"])
    assert executable.is_absolute()
    return executable


@pytest.fixture
def external_mesher(official_su2_validator_path: Path):
    """Construct meshers with the trusted validator injected explicitly."""

    def create(**kwargs) -> GmshMesher:
        return GmshMesher(
            su2_validator_path=official_su2_validator_path,
            **kwargs,
        )

    return create


@pytest.fixture
def synthetic_step_factory():
    created_paths: list[Path] = []

    def write(
        path: Path,
        *,
        kind: str = "wing",
        scale: float = 1.0,
    ) -> Path:
        """Write STEP in OCC's millimetre frame without reading its text."""

        gmsh.initialize()
        previous_target_unit = gmsh.option.getString("Geometry.OCCTargetUnit")
        try:
            gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
            gmsh.model.add(f"mesh-fixture-{uuid4().hex}")
            if kind == "wing":
                _add_wing_prism(scale=scale, x_offset=0.0)
            elif kind == "two_wings":
                _add_wing_prism(scale=scale, x_offset=-8000.0 * scale)
                _add_wing_prism(scale=scale, x_offset=8000.0 * scale)
            elif kind == "open_shell":
                gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, 1000.0, 2000.0)
            elif kind == "curve_only":
                gmsh.model.occ.addLine(
                    gmsh.model.occ.addPoint(0.0, 0.0, 0.0),
                    gmsh.model.occ.addPoint(1000.0, 0.0, 0.0),
                )
            elif kind == "zero_volume":
                # OCC retains this degenerate cylinder as a volume entity with
                # exactly zero mass, and STEP round-trip preserves that fact.
                gmsh.model.occ.addCylinder(0.0, 0.0, 0.0, 1000.0, 0.0, 0.0, 0.0)
            else:
                raise ValueError(kind)
            gmsh.model.occ.synchronize()
            gmsh.write(str(path))
            created_paths.append(path)
            return path
        finally:
            gmsh.option.setString("Geometry.OCCTargetUnit", previous_target_unit)
            gmsh.finalize()

    yield write

    assert not gmsh.isInitialized()


def _add_wing_prism(*, scale: float, x_offset: float) -> int:
    """Create a closed constant-section wing in the original CAD frame."""

    x_root = x_offset - 3000.0 * scale
    points = [
        gmsh.model.occ.addPoint(x_root, 0.0, -1000.0 * scale),
        gmsh.model.occ.addPoint(x_root, 200.0 * scale, -300.0 * scale),
        gmsh.model.occ.addPoint(x_root, 0.0, 1000.0 * scale),
        gmsh.model.occ.addPoint(x_root, -200.0 * scale, -300.0 * scale),
    ]
    curves = [
        gmsh.model.occ.addLine(points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]
    wire = gmsh.model.occ.addWire(curves)
    section = gmsh.model.occ.addPlaneSurface([wire])
    extruded = gmsh.model.occ.extrude(
        [(2, section)], 6000.0 * scale, 0.0, 0.0
    )
    return next(tag for dimension, tag in extruded if dimension == 3)
