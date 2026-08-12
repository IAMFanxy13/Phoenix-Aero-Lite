"""Reference quantities derived from user-picked, tagged wing surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
import pyvista as pv


@dataclass(frozen=True, slots=True)
class WingReferenceResult:
    surface_tags: tuple[int, ...]
    s_ref_m2: float
    c_ref_m: float
    span_m: float
    projected_positive_m2: float
    projected_negative_m2: float
    confidence: str
    rationale_zh: str


def calculate_wing_reference(
    mesh_path: Path,
    surface_tags: tuple[int, ...],
    *,
    up_axis: str,
    span_axis: str,
) -> WingReferenceResult:
    """Calculate projected planform area and mean geometric chord.

    The preview mesh carries real Gmsh OCC face ids in ``CellEntityIds``.
    Projection is evaluated on both sides of the selected shell and the larger
    one-sided value is used, avoiding double-counting upper and lower skins.
    """

    tags = tuple(sorted({int(tag) for tag in surface_tags}))
    if not tags:
        raise ValueError("WING_SURFACE_SELECTION_EMPTY")
    dataset = pv.read(Path(mesh_path).resolve(strict=True))
    if "CellEntityIds" not in dataset.cell_data:
        raise ValueError("WING_SURFACE_TAGS_MISSING")
    entity_ids = np.asarray(dataset.cell_data["CellEntityIds"], dtype=int)
    available = set(int(value) for value in np.unique(entity_ids))
    if not set(tags).issubset(available):
        raise ValueError("WING_SURFACE_TAG_INVALID")

    selected = dataset.extract_cells(np.isin(entity_ids, tags)).extract_surface(
        algorithm="dataset_surface"
    )
    if selected.n_cells <= 0 or selected.n_points <= 0:
        raise ValueError("WING_SURFACE_SELECTION_EMPTY")
    triangles = selected.triangulate().compute_normals(
        cell_normals=True,
        point_normals=False,
        consistent_normals=False,
        auto_orient_normals=False,
    )
    sized = triangles.compute_cell_sizes(length=False, area=True, volume=False)
    areas = np.asarray(sized.cell_data["Area"], dtype=float)
    normals = np.asarray(triangles.cell_data["Normals"], dtype=float)
    up = _axis_vector(up_axis)
    span_direction = _axis_vector(span_axis)
    dots = normals @ up
    positive = float(np.sum(areas * np.clip(dots, 0.0, None)))
    negative = float(np.sum(areas * np.clip(-dots, 0.0, None)))
    reference_area = max(positive, negative)
    projections = np.asarray(selected.points, dtype=float) @ span_direction
    span = float(np.ptp(projections))
    full_span = float(
        np.ptp(np.asarray(dataset.points, dtype=float) @ span_direction)
    )
    if (
        not math.isfinite(reference_area)
        or not math.isfinite(span)
        or reference_area <= 0.0
        or span <= 0.0
    ):
        raise ValueError("WING_REFERENCE_CALCULATION_INVALID")
    chord = reference_area / span
    confidence = (
        "medium"
        if len(tags) >= 2 or (full_span > 0.0 and span / full_span >= 0.8)
        else "low"
    )
    rationale = (
        f"使用用户点选的 {len(tags)} 个真实 OCC 曲面；沿 {up_axis} 投影，"
        "分别累计正、反两侧三角形投影并取较大值，避免上下蒙皮重复计数；"
        f"翼展沿 {span_axis} 取所选网格点极差，c_ref=S_ref/span。"
    )
    return WingReferenceResult(
        surface_tags=tags,
        s_ref_m2=reference_area,
        c_ref_m=chord,
        span_m=span,
        projected_positive_m2=positive,
        projected_negative_m2=negative,
        confidence=confidence,
        rationale_zh=rationale,
    )


def _axis_vector(axis: str) -> np.ndarray:
    normalized = str(axis).upper()
    try:
        vector = {
            "+X": (1.0, 0.0, 0.0),
            "-X": (-1.0, 0.0, 0.0),
            "+Y": (0.0, 1.0, 0.0),
            "-Y": (0.0, -1.0, 0.0),
            "+Z": (0.0, 0.0, 1.0),
            "-Z": (0.0, 0.0, -1.0),
        }[normalized]
    except KeyError:
        raise ValueError("MODEL_PARAMETER_VALUE_INVALID") from None
    return np.asarray(vector, dtype=float)
