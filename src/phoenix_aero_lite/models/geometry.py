"""Immutable geometry inspection values and the approved solver frame mapping."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Mapping, Sequence


Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned bounds whose coordinates are explicitly in metres."""

    minimum_m: Vector3
    maximum_m: Vector3

    @property
    def dimensions_m(self) -> Vector3:
        return tuple(
            maximum - minimum
            for minimum, maximum in zip(self.minimum_m, self.maximum_m, strict=True)
        )

    @property
    def diagonal_m(self) -> float:
        return math.dist(self.minimum_m, self.maximum_m)


@dataclass(frozen=True, slots=True)
class GeometryInspection:
    """Tag-free summary of one STEP import through OpenCASCADE."""

    volume_count: int
    surface_count: int
    bounding_box: BoundingBox
    unit: str
    scale_note: str

    @property
    def bounding_box_min_m(self) -> Vector3:
        return self.bounding_box.minimum_m

    @property
    def bounding_box_max_m(self) -> Vector3:
        return self.bounding_box.maximum_m

    @property
    def dimensions_m(self) -> Vector3:
        return self.bounding_box.dimensions_m

    @property
    def diagonal_m(self) -> float:
        return self.bounding_box.diagonal_m


@dataclass(frozen=True, slots=True)
class SurfacePreviewArtifacts:
    """A real Gmsh surface mesh paired with its tag-free inspection."""

    inspection: GeometryInspection
    mesh_path: Path
    point_count: int
    cell_count: int
    warnings: tuple[str, ...] = ()
    surface_tags: tuple[int, ...] = ()
    mesh_audit: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class CoordinateTransform:
    """Fixed linear/scale/translation record suitable for a case manifest."""

    name: str
    source_frame: str
    target_frame: str
    matrix: Matrix3
    scale: float
    translation_m: Vector3

    def apply(self, original: Sequence[float]) -> Vector3:
        """Return a transformed copy without changing the source coordinates."""

        if len(original) != 3:
            raise ValueError("COORDINATE_VECTOR_MUST_HAVE_THREE_COMPONENTS")
        source = tuple(float(component) for component in original)
        return tuple(
            self.scale * sum(row[index] * source[index] for index in range(3))
            + self.translation_m[row_index]
            for row_index, row in enumerate(self.matrix)
        )

    def to_manifest(self) -> dict[str, object]:
        """Return JSON-native data; angle of attack deliberately has no place here."""

        return {
            "name": self.name,
            "source_frame": self.source_frame,
            "target_frame": self.target_frame,
            "matrix": [list(row) for row in self.matrix],
            "scale": self.scale,
            "translation_m": list(self.translation_m),
        }


ORIGINAL_TO_SU2_TRANSFORM = CoordinateTransform(
    name="original_to_su2",
    source_frame="original_cad",
    target_frame="su2",
    matrix=((0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    scale=1.0,
    translation_m=(0.0, 0.0, 0.0),
)
