"""Deterministic SU2 8.5.0 INC_RANS/SST configuration generation."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import math
import os
from pathlib import Path
import shutil
from types import MappingProxyType
from typing import BinaryIO, Callable, Mapping, Sequence
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from phoenix_aero_lite.models.errors import ParameterValidationError
from phoenix_aero_lite.models.mesh import PhysicalGroupSummary
from phoenix_aero_lite.models.parameters import CaseParameters


_CONFIG_FILENAME = "inc_rans_sst.cfg"
_MESH_FILENAME = "mesh.su2"
_EXPECTED_GROUPS = {
    "fluid": 3,
    "aircraft": 2,
    "farfield": 2,
}
_OFFICIAL_SOURCES = (
    "SU2 v8.5.0 config_template.cfg",
    "SU2 v8.5.0 official incompressible SST test case",
)
_TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[1] / "templates" / "su2"


class Su2ConfigError(ValueError):
    """Stable validation failure at the SU2 configuration boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RenderedSu2Config:
    """Published configuration evidence for downstream run orchestration.

    ``normalized_values`` contains only validated SI values and fixed enums.
    ``official_sources`` identifies the SU2 8.5.0 files whose structure and
    numerical family the local template follows.
    """

    path: Path
    sha256: str
    normalized_values: Mapping[str, object]
    official_sources: tuple[str, str]


def render_su2_config(
    parameters: CaseParameters,
    mesh_path: Path,
    physical_groups: Sequence[PhysicalGroupSummary],
    output_directory: Path,
) -> RenderedSu2Config:
    """Validate, render, and publish a case-local SU2 8.5.0 configuration.

    The body frame is +x forward, +y starboard, +z up. Positive angle of
    attack rotates the freestream velocity toward +z; sideslip is always zero.
    The source mesh is copied to the fixed case-local name ``mesh.su2`` so raw
    caller path text can never become SU2 configuration syntax.
    """

    if not isinstance(parameters, CaseParameters):
        raise Su2ConfigError("SU2_PARAMETERS_INVALID")
    parameter_issues = parameters.validate()
    if parameter_issues:
        raise ParameterValidationError(parameter_issues)
    source_mesh = _validate_mesh_path(mesh_path)
    _validate_physical_groups(physical_groups)
    output = _validate_output_directory(output_directory)

    angle_radians = math.radians(parameters.flow.angle_of_attack_deg)
    velocity = parameters.flow.velocity_m_s
    velocity_vector = (
        _normalize_zero(velocity * math.cos(angle_radians)),
        0.0,
        _normalize_zero(velocity * math.sin(angle_radians)),
    )
    normalized_values = MappingProxyType(
        {
            "su2_version": "8.5.0",
            "solver": "INC_RANS",
            "turbulence_model": "SST",
            "density_kg_m3": float(parameters.flow.density_kg_m3),
            "dynamic_viscosity_pa_s": float(
                parameters.flow.dynamic_viscosity_pa_s
            ),
            "angle_of_attack_deg": float(
                parameters.flow.angle_of_attack_deg
            ),
            "velocity_vector_m_s": velocity_vector,
            "reference_area_m2": float(parameters.reference.s_ref_m2),
            "reference_length_m": float(parameters.reference.c_ref_m),
            "max_iterations": parameters.solver.max_iterations,
            "physical_groups": ("aircraft", "farfield", "fluid"),
            "mesh_filename": _MESH_FILENAME,
            "history_filename": "history.csv",
            "restart_filename": "restart_flow.dat",
            "volume_filename": "flow.vtu",
            "surface_filename": "surface_flow.vtu",
        }
    )
    rendered_text = _render_template(normalized_values)
    rendered_bytes = rendered_text.encode("utf-8")
    digest = hashlib.sha256(rendered_bytes).hexdigest()
    config_path, case_mesh_path = _publish_exclusive(
        output=output,
        source_mesh=source_mesh,
        rendered_bytes=rendered_bytes,
    )
    if not case_mesh_path.is_file():
        raise Su2ConfigError("SU2_OUTPUT_WRITE_FAILED")
    return RenderedSu2Config(
        path=config_path,
        sha256=digest,
        normalized_values=normalized_values,
        official_sources=_OFFICIAL_SOURCES,
    )


def _validate_mesh_path(mesh_path: Path) -> Path:
    if not isinstance(mesh_path, Path):
        raise Su2ConfigError("SU2_MESH_MISSING")
    candidate = mesh_path if mesh_path.is_absolute() else Path.cwd() / mesh_path
    if not candidate.is_file():
        raise Su2ConfigError("SU2_MESH_MISSING")
    candidate = candidate.resolve(strict=True)
    if candidate.stat().st_size <= 0:
        raise Su2ConfigError("SU2_MESH_EMPTY")
    return candidate


def _validate_physical_groups(
    physical_groups: Sequence[PhysicalGroupSummary],
) -> None:
    try:
        groups = tuple(physical_groups)
    except TypeError:
        raise Su2ConfigError("SU2_PHYSICAL_GROUPS_INVALID") from None
    if len(groups) != len(_EXPECTED_GROUPS):
        raise Su2ConfigError("SU2_PHYSICAL_GROUPS_INVALID")
    actual: dict[str, PhysicalGroupSummary] = {}
    for group in groups:
        if (
            not isinstance(group, PhysicalGroupSummary)
            or group.name not in _EXPECTED_GROUPS
            or group.name in actual
            or group.dimension != _EXPECTED_GROUPS[group.name]
            or not isinstance(group.entity_count, int)
            or isinstance(group.entity_count, bool)
            or group.entity_count <= 0
            or len(group.bounding_boxes_m) != group.entity_count
        ):
            raise Su2ConfigError("SU2_PHYSICAL_GROUPS_INVALID")
        actual[group.name] = group
    if set(actual) != set(_EXPECTED_GROUPS):
        raise Su2ConfigError("SU2_PHYSICAL_GROUPS_INVALID")


def _validate_output_directory(output_directory: Path) -> Path:
    if (
        not isinstance(output_directory, Path)
        or not output_directory.name
        or ".." in output_directory.parts
    ):
        raise Su2ConfigError("SU2_OUTPUT_PATH_UNSAFE")
    requested = (
        output_directory
        if output_directory.is_absolute()
        else Path.cwd() / output_directory
    )
    if _has_redirecting_existing_ancestor(requested):
        raise Su2ConfigError("SU2_OUTPUT_PATH_UNSAFE")
    if requested.exists():
        if _is_redirecting_path(requested):
            raise Su2ConfigError("SU2_OUTPUT_PATH_UNSAFE")
        raise Su2ConfigError("SU2_OUTPUT_COLLISION")
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    if output.exists():
        if _is_redirecting_path(output):
            raise Su2ConfigError("SU2_OUTPUT_PATH_UNSAFE")
        raise Su2ConfigError("SU2_OUTPUT_COLLISION")
    return output


def _has_redirecting_existing_ancestor(path: Path) -> bool:
    current = path
    while True:
        if current.exists() and _is_redirecting_path(current):
            return True
        if current.parent == current:
            return False
        current = current.parent


def _is_redirecting_path(path: Path) -> bool:
    if path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    ):
        return True
    try:
        return path.is_file() and path.stat().st_nlink > 1
    except FileNotFoundError:
        return False


def _render_template(values: Mapping[str, object]) -> str:
    # This Jinja environment emits a plain-text SU2 configuration, never HTML.
    # Escaping would corrupt operators and marker syntax; all values are typed
    # and serialized by explicit filters before reaching the template.
    environment = Environment(  # nosec B701
        loader=FileSystemLoader(_TEMPLATE_DIRECTORY),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        newline_sequence="\n",
    )
    environment.filters["su2_number"] = _su2_number
    template = environment.get_template("inc_rans_sst.cfg.j2")
    return template.render(**values)


def _su2_number(value: object) -> str:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise Su2ConfigError("SU2_PARAMETERS_INVALID")
    if value == 0:
        return "0"
    return format(value, ".15g")


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value


def _publish_exclusive(
    *,
    output: Path,
    source_mesh: Path,
    rendered_bytes: bytes,
) -> tuple[Path, Path]:
    config_path = output / _CONFIG_FILENAME
    mesh_path = output / _MESH_FILENAME
    try:
        staging = _create_unique_staging_directory(output.parent)
        _write_durable(
            staging / _MESH_FILENAME,
            lambda destination: _copy_mesh(source_mesh, destination),
        )
        _write_durable(
            staging / _CONFIG_FILENAME,
            lambda destination: destination.write(rendered_bytes),
        )
        _commit_staging_no_replace(staging, output)
    except FileExistsError:
        raise Su2ConfigError("SU2_OUTPUT_COLLISION") from None
    except Su2ConfigError:
        raise
    except OSError as error:
        if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise Su2ConfigError("SU2_OUTPUT_COLLISION") from None
        raise Su2ConfigError("SU2_OUTPUT_WRITE_FAILED") from None
    return config_path, mesh_path


def _create_unique_staging_directory(parent: Path) -> Path:
    for _attempt in range(16):
        staging = parent / f".phoenix-su2-{uuid4().hex}.staging"
        try:
            os.mkdir(_extended_windows_path(staging))
        except FileExistsError:
            continue
        return staging
    raise Su2ConfigError("SU2_OUTPUT_WRITE_FAILED")


def _write_durable(path: Path, write: Callable[[BinaryIO], object]) -> None:
    native_path = _extended_windows_path(path)
    if isinstance(native_path, Path):
        stream_context = native_path.open("xb")
    else:
        stream_context = open(native_path, "xb")
    with stream_context as stream:
        write(stream)
        stream.flush()
        os.fsync(stream.fileno())


def _copy_mesh(source_path: Path, destination: BinaryIO) -> None:
    with source_path.open("rb") as source:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


def _commit_staging_no_replace(staging: Path, output: Path) -> None:
    """Atomically publish the complete staging directory on Windows.

    ``os.rename`` is a same-volume atomic directory rename. On Windows it
    raises ``FileExistsError`` instead of replacing an existing destination;
    Phoenix Aero Lite is a Windows-only workflow and relies on that native
    no-replace contract.
    """

    os.rename(
        _extended_windows_path(staging),
        _extended_windows_path(output),
    )


def _extended_windows_path(path: Path) -> Path | str:
    native = str(path)
    if os.name != "nt" or len(native) < 248 or native.startswith("\\\\?\\"):
        return path
    if native.startswith("\\\\"):
        return "\\\\?\\UNC\\" + native[2:]
    return "\\\\?\\" + native
