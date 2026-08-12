from pathlib import Path

import numpy as np
import pyvista as pv
import pytest

from phoenix_aero_lite.geometry.wing_reference import calculate_wing_reference


def _tagged_wing(path: Path) -> Path:
    points = np.asarray([
        [-1.0, 0.0, -0.2], [0.0, 0.0, -0.2], [0.0, 0.0, 0.2], [-1.0, 0.0, 0.2],
        [0.0, 0.0, -0.2], [1.0, 0.0, -0.2], [1.0, 0.0, 0.2], [0.0, 0.0, 0.2],
    ])
    mesh = pv.PolyData(points, np.asarray([4, 0, 1, 2, 3, 4, 4, 5, 6, 7]))
    mesh.cell_data["CellEntityIds"] = np.asarray([10, 20])
    mesh.save(path)
    return path


def test_calculates_planform_span_and_chord_from_real_tagged_cells(tmp_path: Path):
    mesh = _tagged_wing(tmp_path / "wing.vtk")

    result = calculate_wing_reference(
        mesh, (10, 20), up_axis="+Y", span_axis="+X"
    )

    assert result.surface_tags == (10, 20)
    assert result.s_ref_m2 == pytest.approx(0.8, rel=1e-5)
    assert result.span_m == pytest.approx(2.0, rel=1e-5)
    assert result.c_ref_m == pytest.approx(0.4, rel=1e-5)
    assert result.confidence == "medium"


def test_rejects_unavailable_surface_tag(tmp_path: Path):
    mesh = _tagged_wing(tmp_path / "wing.vtk")

    with pytest.raises(ValueError, match="WING_SURFACE_TAG_INVALID"):
        calculate_wing_reference(mesh, (99,), up_axis="+Y", span_axis="+X")
