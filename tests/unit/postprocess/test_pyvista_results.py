from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv
import pytest

from phoenix_aero_lite.postprocess.pyvista_results import (
    PyVistaResultError,
    ResultDataset,
    load_result,
)


def _grid() -> pv.UnstructuredGrid:
    image = pv.ImageData(dimensions=(8, 7, 6), spacing=(0.2, 0.2, 0.2))
    grid = image.cast_to_unstructured_grid()
    points = grid.points
    grid.point_data["pressure"] = points[:, 0] + points[:, 1]
    grid.point_data["velocity"] = np.column_stack(
        (
            np.ones(grid.n_points),
            0.1 * np.ones(grid.n_points),
            np.zeros(grid.n_points),
        )
    )
    return grid


def test_load_discovers_arrays_and_supports_slice_clip_contour(tmp_path: Path):
    path = tmp_path / "flow.vtu"
    _grid().save(path)
    result = load_result(path)
    assert result.scalar_names == ("pressure",)
    assert result.vector_names == ("velocity",)
    assert result.slice(normal=(1, 0, 0)).n_cells > 0
    assert result.slice(normal=(0, 1, 0), origin=(0, 0.4, 0)).n_points > 0
    assert result.clip(normal=(1, 0, 0)).n_cells > 0
    assert result.contour("pressure", count=3).n_cells > 0


def test_streamlines_and_offscreen_screenshot(tmp_path: Path):
    result = ResultDataset.from_dataset(_grid())
    lines = result.streamlines("velocity", seed_count=25)
    assert lines.n_points > 0
    screenshot = result.screenshot(
        tmp_path / "view.png", scalars="pressure"
    )
    assert screenshot.is_file()
    assert screenshot.stat().st_size > 0


def test_invalid_arrays_seed_count_and_output_collision_are_stable(tmp_path: Path):
    result = ResultDataset.from_dataset(_grid())
    with pytest.raises(PyVistaResultError, match="RESULT_SCALAR_MISSING"):
        result.contour("missing", count=3)
    with pytest.raises(PyVistaResultError, match="RESULT_VECTOR_MISSING"):
        result.streamlines("missing", seed_count=5)
    with pytest.raises(PyVistaResultError, match="STREAMLINE_SEED_COUNT_INVALID"):
        result.streamlines("velocity", seed_count=10001)
    output = tmp_path / "exists.png"
    output.write_bytes(b"keep")
    with pytest.raises(PyVistaResultError, match="RESULT_OUTPUT_COLLISION"):
        result.screenshot(output)
    assert output.read_bytes() == b"keep"


def test_rejects_empty_or_unsupported_result(tmp_path: Path):
    missing = tmp_path / "missing.vtu"
    with pytest.raises(PyVistaResultError, match="RESULT_FILE_MISSING"):
        load_result(missing)
    text = tmp_path / "flow.txt"
    text.write_text("not vtk", encoding="utf-8")
    with pytest.raises(PyVistaResultError, match="RESULT_FORMAT_UNSUPPORTED"):
        load_result(text)
