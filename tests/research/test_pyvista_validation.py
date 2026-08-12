from __future__ import annotations

from scripts.research.validate_pyvista import build_flow_scene


def test_build_flow_scene_generates_streamlines_and_contours():
    grid, streamlines, contour = build_flow_scene()

    assert grid.n_points > 0
    assert streamlines.n_points > 0
    assert contour.n_cells > 0
