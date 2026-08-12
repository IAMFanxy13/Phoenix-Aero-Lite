"""Exercise official PyVista display, contour, streamline and screenshot APIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyvista as pv


def build_flow_scene() -> tuple[pv.ImageData, pv.PolyData, pv.PolyData]:
    """Build a small vector field using the current public streamline API."""
    grid = pv.ImageData(dimensions=(24, 24, 16), spacing=(0.1, 0.1, 0.1))
    points = grid.points
    grid["speed"] = np.linalg.norm(points, axis=1)
    grid["velocity"] = np.column_stack(
        (-points[:, 1], points[:, 0], np.full(len(points), 0.15))
    )
    source = pv.Disc(center=(1.1, 1.1, 0.75), inner=0.05, outer=0.75)
    streamlines = grid.streamlines_from_source(
        source, vectors="velocity", max_length=8.0, initial_step_length=0.05
    )
    contour = grid.contour([1.0, 1.5], scalars="speed")
    return grid, streamlines, contour


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    grid, streamlines, contour = build_flow_scene()

    screenshot = args.output_dir / "pyvista_streamlines.png"
    plotter = pv.Plotter(off_screen=True, window_size=(900, 650))
    plotter.add_mesh(grid.outline(), color="black")
    plotter.add_mesh(contour, scalars="speed", opacity=0.35)
    plotter.add_mesh(streamlines.tube(radius=0.008), scalars="speed")
    plotter.view_isometric()
    plotter.show(screenshot=str(screenshot), auto_close=True)

    result = {
        "pyvista_version": pv.__version__,
        "grid_points": grid.n_points,
        "streamline_points": streamlines.n_points,
        "contour_cells": contour.n_cells,
        "screenshot": str(screenshot.resolve()),
        "screenshot_bytes": screenshot.stat().st_size,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
