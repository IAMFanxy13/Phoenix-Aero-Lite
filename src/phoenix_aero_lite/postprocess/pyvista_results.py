"""PyVista-based CFD result operations; no VTK text or OpenGL reimplementation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image
import pyvista as pv


class PyVistaResultError(ValueError):
    """Stable result-view operation failure."""


@dataclass(frozen=True, slots=True)
class ResultDataset:
    """Validated PyVista dataset plus discovered scalar/vector arrays."""

    dataset: pv.DataSet
    scalar_names: tuple[str, ...]
    vector_names: tuple[str, ...]

    @classmethod
    def from_dataset(cls, dataset: pv.DataSet) -> "ResultDataset":
        """Validate an in-memory PyVista dataset and discover its arrays."""

        if (
            not isinstance(dataset, pv.DataSet)
            or dataset.n_points <= 0
            or dataset.n_cells <= 0
        ):
            raise PyVistaResultError("RESULT_DATASET_EMPTY")
        scalars: set[str] = set()
        vectors: set[str] = set()
        for attributes in (dataset.point_data, dataset.cell_data):
            for name in attributes.keys():
                values = np.asarray(attributes[name])
                if values.ndim == 1:
                    scalars.add(str(name))
                elif values.ndim == 2 and values.shape[1] == 3:
                    vectors.add(str(name))
        return cls(
            dataset=dataset,
            scalar_names=tuple(sorted(scalars)),
            vector_names=tuple(sorted(vectors)),
        )

    def slice(
        self,
        *,
        normal: Sequence[float] = (1.0, 0.0, 0.0),
        origin: Sequence[float] | None = None,
    ) -> pv.PolyData:
        """Return a PyVista planar slice."""

        return self.dataset.slice(
            normal=_vector3(normal, allow_zero=False),
            origin=_vector3(
                self.dataset.center if origin is None else origin,
                allow_zero=True,
            ),
        )

    def clip(
        self,
        *,
        normal: Sequence[float] = (1.0, 0.0, 0.0),
        origin: Sequence[float] | None = None,
        invert: bool = False,
    ) -> pv.DataSet:
        """Return a PyVista plane clip."""

        return self.dataset.clip(
            normal=_vector3(normal, allow_zero=False),
            origin=_vector3(
                self.dataset.center if origin is None else origin,
                allow_zero=True,
            ),
            invert=bool(invert),
        )

    def contour(self, scalar: str, *, count: int = 10) -> pv.PolyData:
        """Generate scalar isosurfaces through PyVista."""

        if scalar not in self.scalar_names:
            raise PyVistaResultError("RESULT_SCALAR_MISSING")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 1 <= count <= 100
        ):
            raise PyVistaResultError("CONTOUR_COUNT_INVALID")
        point_dataset = self._point_dataset_for(scalar)
        result = point_dataset.contour(isosurfaces=count, scalars=scalar)
        if result.n_cells <= 0:
            raise PyVistaResultError("CONTOUR_EMPTY")
        return result

    def streamlines(
        self,
        vector: str,
        *,
        seed_count: int = 100,
    ) -> pv.PolyData:
        """Generate bounded streamline seeds and integrate with PyVista."""

        if vector not in self.vector_names:
            raise PyVistaResultError("RESULT_VECTOR_MISSING")
        if (
            not isinstance(seed_count, int)
            or isinstance(seed_count, bool)
            or not 1 <= seed_count <= 10_000
        ):
            raise PyVistaResultError("STREAMLINE_SEED_COUNT_INVALID")
        point_dataset = self._point_dataset_for(vector)
        bounds = point_dataset.bounds
        center = np.asarray(point_dataset.center)
        spans = [
            bounds.x_max - bounds.x_min,
            bounds.y_max - bounds.y_min,
            bounds.z_max - bounds.z_min,
        ]
        axis = int(np.argmax(spans))
        coordinates = np.tile(center, (seed_count, 1))
        lower = (bounds.x_min, bounds.y_min, bounds.z_min)[axis]
        upper = (bounds.x_max, bounds.y_max, bounds.z_max)[axis]
        coordinates[:, axis] = np.linspace(lower, upper, seed_count)
        source = pv.PolyData(coordinates)
        result = point_dataset.streamlines_from_source(
            source,
            vectors=vector,
            integration_direction="both",
            max_steps=2_000,
        )
        if result.n_points <= 0:
            raise PyVistaResultError("STREAMLINES_EMPTY")
        return result

    def screenshot(
        self,
        output_path: Path,
        *,
        scalars: str | None = None,
    ) -> Path:
        """Render off-screen and publish a PNG without overwriting."""

        if scalars is not None and scalars not in self.scalar_names:
            raise PyVistaResultError("RESULT_SCALAR_MISSING")
        output = _validate_output_path(output_path)
        plotter = pv.Plotter(off_screen=True, window_size=(1280, 720))
        try:
            plotter.add_mesh(
                self.dataset,
                scalars=scalars,
                show_edges=False,
            )
            plotter.view_isometric()
            plotter.reset_camera()
            image = plotter.screenshot(return_img=True)
        finally:
            plotter.close()
        if image is None:
            raise PyVistaResultError("SCREENSHOT_FAILED")
        try:
            with output.open("xb") as destination:
                Image.fromarray(np.asarray(image)).save(destination, format="PNG")
        except FileExistsError:
            raise PyVistaResultError("RESULT_OUTPUT_COLLISION") from None
        except OSError:
            raise PyVistaResultError("SCREENSHOT_FAILED") from None
        return output.resolve(strict=True)

    def _point_dataset_for(self, name: str) -> pv.DataSet:
        if name in self.dataset.point_data:
            return self.dataset
        return self.dataset.cell_data_to_point_data()


def load_result(path: Path) -> ResultDataset:
    """Load VTK/VTU through PyVista's official readers."""

    if not isinstance(path, Path) or not path.is_file():
        raise PyVistaResultError("RESULT_FILE_MISSING")
    if path.suffix.lower() not in {".vtu", ".vtk"}:
        raise PyVistaResultError("RESULT_FORMAT_UNSUPPORTED")
    try:
        dataset = pv.read(path.resolve(strict=True))
    except (OSError, ValueError, RuntimeError):
        raise PyVistaResultError("RESULT_READ_FAILED") from None
    if isinstance(dataset, pv.MultiBlock):
        try:
            dataset = dataset.combine()
        except (ValueError, RuntimeError):
            raise PyVistaResultError("RESULT_READ_FAILED") from None
    return ResultDataset.from_dataset(dataset)


def _vector3(
    value: Sequence[float],
    *,
    allow_zero: bool,
) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)):
        raise PyVistaResultError("RESULT_VECTOR_INVALID")
    try:
        values = tuple(value)
    except TypeError:
        raise PyVistaResultError("RESULT_VECTOR_INVALID") from None
    if (
        len(values) != 3
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(item)
            for item in values
        )
        or (not allow_zero and values == (0, 0, 0))
    ):
        raise PyVistaResultError("RESULT_VECTOR_INVALID")
    return (float(values[0]), float(values[1]), float(values[2]))


def _validate_output_path(path: Path) -> Path:
    if (
        not isinstance(path, Path)
        or path.suffix.lower() != ".png"
        or not path.name
        or ".." in path.parts
    ):
        raise PyVistaResultError("RESULT_OUTPUT_PATH_UNSAFE")
    requested = path if path.is_absolute() else Path.cwd() / path
    current = requested.parent
    while True:
        if current.exists() and (
            current.is_symlink()
            or (hasattr(current, "is_junction") and current.is_junction())
        ):
            raise PyVistaResultError("RESULT_OUTPUT_PATH_UNSAFE")
        if current.parent == current:
            break
        current = current.parent
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    if output.exists():
        raise PyVistaResultError("RESULT_OUTPUT_COLLISION")
    return output
