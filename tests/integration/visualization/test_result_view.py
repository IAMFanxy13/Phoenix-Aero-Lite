from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv
from PySide6.QtWidgets import QApplication

from phoenix_aero_lite.app.widgets.result_view import ResultView


def test_result_view_embeds_pyvista_without_showing_window(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    grid = pv.ImageData(dimensions=(5, 5, 5)).cast_to_unstructured_grid()
    grid.point_data["p"] = grid.points[:, 0]
    grid.point_data["U"] = np.tile((1.0, 0.0, 0.0), (grid.n_points, 1))
    path = tmp_path / "flow.vtu"
    grid.save(path)
    view = ResultView()
    try:
        assert view.load_file(path)
        assert view.show_slice()
        assert view.show_clip()
        assert view.show_contour("p", 2)
        assert view.show_streamlines("U", 8)
    finally:
        view.close()
        app.processEvents()
