"""Persistent model inspection and preview service for the local Web app."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
import math
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from phoenix_aero_lite.geometry.gmsh_geometry import GmshGeometryAdapter
from phoenix_aero_lite.geometry.wing_reference import (
    WingReferenceResult,
    calculate_wing_reference,
)
from phoenix_aero_lite.models.geometry import SurfacePreviewArtifacts
from phoenix_aero_lite.models.provenance import (
    Confidence,
    ParameterSource,
    ProvenancedValue,
)
from phoenix_aero_lite.visualization.web_scene import (
    InteractiveScene,
    export_interactive_surface,
)
from phoenix_aero_lite.web.models import MAX_STEP_BYTES


class ModelState(str, Enum):
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ModelSnapshot:
    model_id: str
    state: ModelState
    created_at: str
    model_directory: Path
    original_filename: str
    source_sha256: str
    inspection: Mapping[str, object]
    preview_point_count: int
    preview_cell_count: int
    artifacts: Mapping[str, str]
    parameters: Mapping[str, Mapping[str, object]]
    warnings: tuple[str, ...] = ()
    selectable_surface_tags: tuple[int, ...] = ()
    selected_surface_tags: tuple[int, ...] = ()
    wing_reference: Mapping[str, object] | None = None
    mesh_audit: Mapping[str, object] | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "model_directory": str(self.model_directory),
            "original_filename": self.original_filename,
            "source_sha256": self.source_sha256,
            "inspection": dict(self.inspection),
            "preview_point_count": self.preview_point_count,
            "preview_cell_count": self.preview_cell_count,
            "artifacts": dict(self.artifacts),
            "parameters": {
                name: dict(value) for name, value in self.parameters.items()
            },
            "warnings": list(self.warnings),
            "selectable_surface_tags": list(self.selectable_surface_tags),
            "selected_surface_tags": list(self.selected_surface_tags),
            "wing_reference": (
                dict(self.wing_reference) if self.wing_reference is not None else None
            ),
            "mesh_audit": dict(self.mesh_audit or {}),
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ModelSnapshot":
        return cls(
            model_id=str(payload["model_id"]),
            state=ModelState(str(payload["state"])),
            created_at=str(payload["created_at"]),
            model_directory=Path(str(payload["model_directory"])),
            original_filename=str(payload["original_filename"]),
            source_sha256=str(payload["source_sha256"]),
            inspection=dict(payload.get("inspection", {})),
            preview_point_count=int(payload.get("preview_point_count", 0)),
            preview_cell_count=int(payload.get("preview_cell_count", 0)),
            artifacts=dict(payload.get("artifacts", {})),
            parameters={
                str(name): dict(value)
                for name, value in dict(payload.get("parameters", {})).items()
            },
            warnings=tuple(str(value) for value in payload.get("warnings", ())),
            selectable_surface_tags=tuple(
                int(value) for value in payload.get("selectable_surface_tags", ())
            ),
            selected_surface_tags=tuple(
                int(value) for value in payload.get("selected_surface_tags", ())
            ),
            wing_reference=(
                dict(payload["wing_reference"])
                if payload.get("wing_reference") is not None
                else None
            ),
            mesh_audit=dict(payload.get("mesh_audit", {})),
            error_code=(
                str(payload["error_code"])
                if payload.get("error_code") is not None
                else None
            ),
        )


PreviewBuilder = Callable[[Path, Path], SurfacePreviewArtifacts]
SceneBuilder = Callable[[Path, Path], InteractiveScene]
WingReferenceCalculator = Callable[..., WingReferenceResult]


class LocalModelService:
    """Own uploaded copies and task-scoped browser previews."""

    def __init__(
        self,
        root: Path,
        *,
        preview_builder: PreviewBuilder | None = None,
        scene_builder: SceneBuilder | None = None,
        wing_reference_calculator: WingReferenceCalculator | None = None,
    ) -> None:
        self._root = Path(root).resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)
        adapter = GmshGeometryAdapter()
        self._preview_builder = preview_builder or adapter.build_surface_preview
        self._scene_builder = scene_builder or export_interactive_surface
        self._wing_reference_calculator = (
            wing_reference_calculator or calculate_wing_reference
        )
        self._snapshots: dict[str, ModelSnapshot] = {}
        self._restore()

    @property
    def root(self) -> Path:
        return self._root

    def create(self, filename: str, content: bytes) -> ModelSnapshot:
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".step", ".stp"}:
            raise ValueError("MODEL_MUST_BE_STEP")
        if not content:
            raise ValueError("MODEL_EMPTY")
        if len(content) > MAX_STEP_BYTES:
            raise ValueError("MODEL_TOO_LARGE")

        model_id = uuid4().hex
        directory = (self._root / model_id).resolve(strict=False)
        if not directory.is_relative_to(self._root):
            raise RuntimeError("MODEL_DIRECTORY_INVALID")
        source = directory / "input" / "model.step"
        _write_bytes_atomic(source, content)
        preview_mesh = directory / "preview" / "surface.vtk"
        preview_mesh.parent.mkdir(parents=True, exist_ok=True)
        preview = self._preview_builder(source, preview_mesh)
        scene = self._scene_builder(
            preview.mesh_path, directory / "preview" / "preview.html"
        )
        inspection = preview.inspection
        snapshot = ModelSnapshot(
            model_id=model_id,
            state=ModelState.READY,
            created_at=datetime.now(timezone.utc).isoformat(),
            model_directory=directory,
            original_filename=Path(filename).name,
            source_sha256=hashlib.sha256(content).hexdigest(),
            inspection={
                "volume_count": inspection.volume_count,
                "surface_count": inspection.surface_count,
                "bounding_box_min_m": list(inspection.bounding_box_min_m),
                "bounding_box_max_m": list(inspection.bounding_box_max_m),
                "dimensions_m": list(inspection.dimensions_m),
                "geometry_center_m": [
                    (minimum + maximum) / 2.0
                    for minimum, maximum in zip(
                        inspection.bounding_box_min_m,
                        inspection.bounding_box_max_m,
                        strict=True,
                    )
                ],
                "unit": inspection.unit,
                "scale_note": inspection.scale_note,
            },
            preview_point_count=scene.point_count,
            preview_cell_count=scene.cell_count,
            artifacts={
                "preview.html": str(scene.output_path),
                "surface.vtk": str(preview.mesh_path),
            },
            parameters=_default_parameters(inspection),
            warnings=preview.warnings,
            mesh_audit=dict(preview.mesh_audit or {}),
            selectable_surface_tags=(
                scene.selectable_surface_tags or preview.surface_tags
            ),
        )
        self._snapshots[model_id] = snapshot
        self._persist(snapshot)
        return snapshot

    def override_parameter(
        self, model_id: str, name: str, value: object
    ) -> ModelSnapshot:
        return self.override_parameters(model_id, {name: value})

    def override_parameters(
        self, model_id: str, values: Mapping[str, object]
    ) -> ModelSnapshot:
        """Validate and persist related user overrides as one atomic update."""

        snapshot = self.get(model_id)
        editable = {
            "s_ref_m2", "c_ref_m", "span_m",
            "nose_axis", "up_axis", "span_axis",
        }
        if not isinstance(values, Mapping) or not values:
            raise ValueError("MODEL_PARAMETER_VALUES_INVALID")
        if any(name not in editable for name in values):
            raise ValueError("MODEL_PARAMETER_NOT_EDITABLE")

        normalized_values: dict[str, float | str] = {}
        numeric = {"s_ref_m2", "c_ref_m", "span_m"}
        for name, value in values.items():
            if name in numeric:
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or float(value) <= 0
                ):
                    raise ValueError("MODEL_PARAMETER_VALUE_INVALID")
                normalized_values[name] = float(value)
            else:
                normalized = str(value).upper()
                if normalized not in {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}:
                    raise ValueError("MODEL_PARAMETER_VALUE_INVALID")
                normalized_values[name] = normalized

        prospective = {
            axis: str(snapshot.parameters[axis]["current_value"]).upper()
            for axis in ("nose_axis", "up_axis", "span_axis")
        }
        prospective.update(
            {
                name: str(value)
                for name, value in normalized_values.items()
                if name in prospective
            }
        )
        if len({axis[-1] for axis in prospective.values()}) != 3:
            raise ValueError("MODEL_ORIENTATION_AXES_CONFLICT")

        parameters = {
            key: dict(item) for key, item in snapshot.parameters.items()
        }
        updated_at = datetime.now(timezone.utc).isoformat()
        for name, value in normalized_values.items():
            try:
                current = ProvenancedValue.from_dict(dict(parameters[name]))
            except KeyError:
                raise ValueError("MODEL_PARAMETER_NOT_FOUND") from None
            parameters[name] = current.with_user_value(
                value,
                confirmed=True,
                updated_at=updated_at,
            ).to_dict()
        updated = replace(
            snapshot,
            parameters=parameters,
        )
        self._snapshots[model_id] = updated
        self._persist(updated)
        return updated

    def restore_parameter(self, model_id: str, name: str) -> ModelSnapshot:
        """Restore one detected value while retaining its audit timestamp."""

        snapshot = self.get(model_id)
        parameters = {
            key: dict(item) for key, item in snapshot.parameters.items()
        }
        try:
            current = ProvenancedValue.from_dict(dict(parameters[name]))
        except KeyError:
            raise ValueError("MODEL_PARAMETER_NOT_FOUND") from None
        parameters[name] = current.restore_detected(
            updated_at=datetime.now(timezone.utc).isoformat()
        ).to_dict()
        updated = replace(snapshot, parameters=parameters)
        self._snapshots[model_id] = updated
        self._persist(updated)
        return updated

    def select_wing_surfaces(
        self, model_id: str, surface_tags: tuple[int, ...]
    ) -> ModelSnapshot:
        snapshot = self.get(model_id)
        tags = tuple(sorted({int(value) for value in surface_tags}))
        if not tags:
            updated = replace(
                snapshot,
                selected_surface_tags=(),
                wing_reference=None,
            )
            self._snapshots[model_id] = updated
            self._persist(updated)
            return updated
        if not set(tags).issubset(set(snapshot.selectable_surface_tags)):
            raise ValueError("WING_SURFACE_TAG_INVALID")
        result = self._wing_reference_calculator(
            snapshot.model_directory / "preview" / "surface.vtk",
            tags,
            up_axis=str(snapshot.parameters["up_axis"]["current_value"]),
            span_axis=str(snapshot.parameters["span_axis"]["current_value"]),
        )
        confidence = Confidence(result.confidence)
        computed = {
            "s_ref_m2": ("m²", result.s_ref_m2),
            "c_ref_m": ("m", result.c_ref_m),
            "span_m": ("m", result.span_m),
        }
        parameters = {
            key: dict(value) for key, value in snapshot.parameters.items()
        }
        for name, (unit, value) in computed.items():
            parameters[name] = ProvenancedValue(
                name=name,
                unit=unit,
                detected_value=value,
                current_value=value,
                source=ParameterSource.SOFTWARE_COMPUTED,
                rationale=result.rationale_zh,
                confidence=confidence,
                confirmed=True,
            ).to_dict()
        reference = {
            "surface_tags": list(result.surface_tags),
            "s_ref_m2": result.s_ref_m2,
            "c_ref_m": result.c_ref_m,
            "span_m": result.span_m,
            "projected_positive_m2": result.projected_positive_m2,
            "projected_negative_m2": result.projected_negative_m2,
            "confidence": result.confidence,
            "rationale_zh": result.rationale_zh,
        }
        updated = replace(
            snapshot,
            selected_surface_tags=result.surface_tags,
            wing_reference=reference,
            parameters=parameters,
        )
        self._snapshots[model_id] = updated
        self._persist(updated)
        return updated

    def get(self, model_id: str) -> ModelSnapshot:
        try:
            return self._snapshots[model_id]
        except KeyError:
            raise KeyError("MODEL_NOT_FOUND") from None

    def list(self) -> tuple[ModelSnapshot, ...]:
        return tuple(
            sorted(self._snapshots.values(), key=lambda item: item.created_at)
        )

    def _persist(self, snapshot: ModelSnapshot) -> None:
        path = snapshot.model_directory / "model.json"
        encoded = json.dumps(
            snapshot.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True
        ).encode("utf-8") + b"\n"
        _write_bytes_atomic(path, encoded)

    def _restore(self) -> None:
        for path in self._root.glob("*/model.json"):
            try:
                snapshot = ModelSnapshot.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            self._snapshots[snapshot.model_id] = snapshot


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _default_parameters(inspection) -> dict[str, dict[str, object]]:
    dimensions = inspection.dimensions_m
    axis_names = ("X", "Y", "Z")
    ordered = sorted(range(3), key=lambda index: dimensions[index], reverse=True)
    span_index, length_index, height_index = ordered
    span_axis = f"+{axis_names[span_index]}"
    up_axis = f"+{axis_names[height_index]}"
    nose_axis = (
        "-Z" if axis_names[length_index] == "Z" else f"+{axis_names[length_index]}"
    )
    values = (
        ProvenancedValue(
            "span_m", "m", dimensions[span_index], dimensions[span_index],
            ParameterSource.SOFTWARE_COMPUTED,
            "将包围盒最长轴作为翼展候选；这只是几何候选，仍需在三维模型中确认主翼。",
            Confidence.MEDIUM, False,
        ),
        ProvenancedValue(
            "length_m", "m", dimensions[length_index], dimensions[length_index],
            ParameterSource.SOFTWARE_COMPUTED,
            "将除翼展轴和最短轴外的包围盒方向作为机身长度候选。",
            Confidence.MEDIUM, False,
        ),
        ProvenancedValue(
            "height_m", "m", dimensions[height_index], dimensions[height_index],
            ParameterSource.SOFTWARE_COMPUTED,
            "将包围盒最短轴尺寸作为高度候选。",
            Confidence.MEDIUM, False,
        ),
        ProvenancedValue(
            "nose_axis", "", nose_axis, nose_axis, ParameterSource.SOFTWARE_COMPUTED,
            "由中间长度轴给出方向轴候选，但 STEP 不含机头正负语义，当前符号未解决，必须人工确认。",
            Confidence.UNRESOLVED, False,
        ),
        ProvenancedValue(
            "up_axis", "", up_axis, up_axis, ParameterSource.SOFTWARE_COMPUTED,
            "由包围盒最短轴给出上方轴候选；正负符号仍需人工确认。",
            Confidence.LOW, False,
        ),
        ProvenancedValue(
            "span_axis", "", span_axis, span_axis, ParameterSource.SOFTWARE_COMPUTED,
            "当前最长包围盒方向作为翼展轴候选，必须结合三维主翼确认。",
            Confidence.MEDIUM, False,
        ),
        ProvenancedValue(
            "s_ref_m2", "m²", "unresolved", "unresolved", ParameterSource.SOFTWARE_DEFAULT,
            "尚未完成主翼表面选择，不能从包围盒可靠推断参考面积。",
            Confidence.UNRESOLVED, False,
        ),
        ProvenancedValue(
            "c_ref_m", "m", "unresolved", "unresolved", ParameterSource.SOFTWARE_DEFAULT,
            "尚未完成主翼表面选择，不能从包围盒可靠推断参考弦长。",
            Confidence.UNRESOLVED, False,
        ),
    )
    return {item.name: item.to_dict() for item in values}
