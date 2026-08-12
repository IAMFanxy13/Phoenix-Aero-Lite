from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv

from phoenix_aero_lite.postprocess.pyvista_results import ResultDataset


def test_offscreen_result_pipeline_writes_real_png(tmp_path: Path):
    grid = pv.ImageData(dimensions=(6, 6, 6)).cast_to_unstructured_grid()
    grid.point_data["p"] = grid.points[:, 0]
    grid.point_data["U"] = np.tile((1.0, 0.0, 0.0), (grid.n_points, 1))
    result = ResultDataset.from_dataset(grid)
    assert result.slice().n_points > 0
    assert result.clip().n_points > 0
    assert result.contour("p", count=2).n_points > 0
    assert result.streamlines("U", seed_count=12).n_points > 0
    png = result.screenshot(tmp_path / "result.png", scalars="p")
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
