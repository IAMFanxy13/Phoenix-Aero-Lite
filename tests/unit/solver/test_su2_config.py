"""Golden and boundary tests for the SU2 8.5.0 INC_RANS/SST config."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError, replace
import errno
import hashlib
import math
import os
from pathlib import Path

import pytest

from phoenix_aero_lite.models.errors import ParameterValidationError
from phoenix_aero_lite.models.geometry import BoundingBox
from phoenix_aero_lite.models.mesh import PhysicalGroupSummary
from phoenix_aero_lite.models.parameters import (
    AircraftParameters,
    CaseParameters,
    FlowParameters,
    MeshMode,
    MeshParameters,
    OutputParameters,
    ReferenceParameters,
    SolverParameters,
)
from phoenix_aero_lite.solver.su2_config import (
    Su2ConfigError,
    render_su2_config,
)


def _case(output: Path, *, angle_deg: float = 0.0) -> CaseParameters:
    return CaseParameters(
        flow=FlowParameters(
            velocity_m_s=50.0,
            density_kg_m3=1.225,
            dynamic_viscosity_pa_s=1.7894e-5,
            angle_of_attack_deg=angle_deg,
        ),
        reference=ReferenceParameters(s_ref_m2=16.2, c_ref_m=1.5),
        aircraft=AircraftParameters(mass_kg=750.0),
        mesh=MeshParameters(mode=MeshMode.PREVIEW, target_cell_size_m=0.5),
        solver=SolverParameters(max_iterations=250),
        output=OutputParameters(output_directory=output),
    )


def _bounds() -> BoundingBox:
    return BoundingBox(
        minimum_m=(-1.0, -1.0, -1.0),
        maximum_m=(1.0, 1.0, 1.0),
    )


def _groups() -> tuple[PhysicalGroupSummary, ...]:
    bounds = _bounds()
    return (
        PhysicalGroupSummary("fluid", 3, 1, (bounds,)),
        PhysicalGroupSummary("aircraft", 2, 1, (bounds,)),
        PhysicalGroupSummary("farfield", 2, 6, (bounds,) * 6),
    )


def _mesh(path: Path, payload: bytes = b"synthetic SU2 mesh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_render_matches_complete_golden_and_returns_immutable_metadata(
    tmp_path: Path,
):
    source_mesh = _mesh(tmp_path / "source" / "external_flow.su2")

    rendered = render_su2_config(
        _case(tmp_path / "ignored-model-output"),
        source_mesh,
        _groups(),
        tmp_path / "case",
    )

    expected = (
        Path(__file__).resolve().parents[2]
        / "golden"
        / "su2"
        / "inc_rans_sst_expected.cfg"
    ).read_bytes()
    assert rendered.path == (tmp_path / "case" / "inc_rans_sst.cfg").resolve()
    assert rendered.path.read_bytes() == expected
    assert rendered.sha256 == hashlib.sha256(expected).hexdigest()
    assert (tmp_path / "case" / "mesh.su2").read_bytes() == source_mesh.read_bytes()
    assert rendered.normalized_values["su2_version"] == "8.5.0"
    assert rendered.normalized_values["velocity_vector_m_s"] == (50.0, 0.0, 0.0)
    assert rendered.normalized_values["reference_area_m2"] == 16.2
    assert rendered.normalized_values["reference_length_m"] == 1.5
    assert rendered.normalized_values["max_iterations"] == 250
    assert rendered.official_sources == (
        "SU2 v8.5.0 config_template.cfg",
        "SU2 v8.5.0 official incompressible SST test case",
    )
    with pytest.raises(FrozenInstanceError):
        rendered.path = tmp_path / "changed.cfg"  # type: ignore[misc]
    with pytest.raises(TypeError):
        rendered.normalized_values["max_iterations"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    ("angle_deg", "expected"),
    [
        (0.0, (50.0, 0.0, 0.0)),
        (30.0, (25.0 * math.sqrt(3.0), 0.0, 25.0)),
        (-30.0, (25.0 * math.sqrt(3.0), 0.0, -25.0)),
    ],
)
def test_velocity_vector_uses_body_xz_plane_without_sideslip(
    tmp_path: Path,
    angle_deg: float,
    expected: tuple[float, float, float],
):
    rendered = render_su2_config(
        _case(tmp_path, angle_deg=angle_deg),
        _mesh(tmp_path / f"mesh-{angle_deg}.su2"),
        _groups(),
        tmp_path / f"case-{angle_deg}",
    )

    assert rendered.normalized_values["velocity_vector_m_s"] == pytest.approx(expected)
    text = rendered.path.read_text(encoding="utf-8")
    assert "INC_VELOCITY_INIT= (" in text
    assert "AOA=" not in text


def test_render_is_byte_deterministic_across_source_and_output_paths(
    tmp_path: Path,
):
    first = render_su2_config(
        _case(tmp_path),
        _mesh(tmp_path / "one.su2", b"same mesh"),
        _groups(),
        tmp_path / "first",
    )
    second = render_su2_config(
        _case(tmp_path),
        _mesh(tmp_path / "nested" / "two.su2", b"same mesh"),
        tuple(reversed(_groups())),
        tmp_path / "second",
    )

    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.sha256 == second.sha256
    assert first.normalized_values == second.normalized_values


def test_paths_with_spaces_and_metacharacters_never_enter_cfg_syntax(
    tmp_path: Path,
):
    hostile = "air craft &amp; $(echo owned)%!^;#"
    source_mesh = _mesh(tmp_path / hostile / "mesh % input.su2")
    rendered = render_su2_config(
        _case(tmp_path),
        source_mesh,
        _groups(),
        tmp_path / hostile / "case output",
    )

    text = rendered.path.read_text(encoding="utf-8")
    assert hostile not in text
    assert str(tmp_path) not in text
    assert "MESH_FILENAME= mesh.su2" in text
    assert "CONV_FILENAME= history" in text
    assert "RESTART_FILENAME= restart_flow.dat" in text
    assert "VOLUME_FILENAME= flow" in text
    assert "SURFACE_FILENAME= surface_flow" in text


@pytest.mark.parametrize(
    "bad_flow",
    [
        FlowParameters(float("nan"), 1.225, 1.8e-5, 0.0),
        FlowParameters(50.0, float("inf"), 1.8e-5, 0.0),
        FlowParameters(50.0, 1.225, float("-inf"), 0.0),
        FlowParameters(50.0, 1.225, 1.8e-5, float("nan")),
    ],
)
def test_non_finite_flow_values_are_rejected_before_writing(
    tmp_path: Path,
    bad_flow: FlowParameters,
):
    case = replace(_case(tmp_path), flow=bad_flow)

    with pytest.raises(ParameterValidationError) as error:
        render_su2_config(
            case,
            _mesh(tmp_path / "mesh.su2"),
            _groups(),
            tmp_path / "case",
        )

    assert "PARAMETER_VALUE_MUST_BE_FINITE" in str(error.value)
    assert not (tmp_path / "case").exists()


@pytest.mark.parametrize(
    ("groups", "code"),
    [
        (_groups()[:-1], "SU2_PHYSICAL_GROUPS_INVALID"),
        (_groups() + (_groups()[0],), "SU2_PHYSICAL_GROUPS_INVALID"),
        (
            (
                replace(_groups()[0], name="fluid\nMARKER_FAR= ( injected )"),
                *_groups()[1:],
            ),
            "SU2_PHYSICAL_GROUPS_INVALID",
        ),
        (
            (replace(_groups()[0], dimension=2), *_groups()[1:]),
            "SU2_PHYSICAL_GROUPS_INVALID",
        ),
        (
            (_groups()[0], replace(_groups()[1], entity_count=0), _groups()[2]),
            "SU2_PHYSICAL_GROUPS_INVALID",
        ),
        (
            (
                _groups()[0],
                replace(_groups()[1], bounding_boxes_m=()),
                _groups()[2],
            ),
            "SU2_PHYSICAL_GROUPS_INVALID",
        ),
    ],
)
def test_only_exact_nonempty_durable_physical_groups_are_accepted(
    tmp_path: Path,
    groups: tuple[PhysicalGroupSummary, ...],
    code: str,
):
    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "mesh.su2"),
            groups,
            tmp_path / "case",
        )

    assert error.value.code == code
    assert not (tmp_path / "case").exists()


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("missing", "SU2_MESH_MISSING"),
        ("empty", "SU2_MESH_EMPTY"),
        ("directory", "SU2_MESH_MISSING"),
    ],
)
def test_missing_empty_or_non_file_mesh_is_rejected(
    tmp_path: Path,
    kind: str,
    code: str,
):
    mesh = tmp_path / "input.su2"
    if kind == "empty":
        mesh.write_bytes(b"")
    elif kind == "directory":
        mesh.mkdir()

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(_case(tmp_path), mesh, _groups(), tmp_path / "case")

    assert error.value.code == code
    assert not (tmp_path / "case").exists()


@pytest.mark.parametrize("collision", ["inc_rans_sst.cfg", "mesh.su2"])
def test_existing_case_artifacts_are_never_overwritten(
    tmp_path: Path,
    collision: str,
):
    output = tmp_path / "case"
    output.mkdir()
    existing = output / collision
    existing.write_bytes(b"keep me")

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_COLLISION"
    assert existing.read_bytes() == b"keep me"
    assert {path.name for path in output.iterdir()} == {collision}


def test_existing_empty_output_directory_is_a_collision(tmp_path: Path):
    output = tmp_path / "case"
    output.mkdir()

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_COLLISION"
    assert output.is_dir()
    assert not list(output.iterdir())


def test_publication_uses_durable_sibling_staging_and_atomic_directory_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"
    opened_exclusively: list[Path] = []
    synced_descriptors: list[int] = []
    atomic_renames: list[tuple[Path, Path]] = []
    real_open = Path.open
    real_builtin_open = builtins.open
    real_fsync = os.fsync
    real_rename = os.rename

    def track_open(self: Path, mode: str = "r", *args, **kwargs):
        if mode == "xb" and self.parent.name.endswith(".staging"):
            opened_exclusively.append(self)
        return real_open(self, mode, *args, **kwargs)

    def track_fsync(descriptor: int):
        synced_descriptors.append(descriptor)
        return real_fsync(descriptor)

    def track_rename(source, destination, *args, **kwargs):
        source_path = _ordinary_windows_path(source)
        destination_path = _ordinary_windows_path(destination)
        assert source_path.parent == output.parent
        assert source_path.name.startswith(".phoenix-su2-")
        assert source_path.name.endswith(".staging")
        assert destination_path == output
        for name in ("mesh.su2", "inc_rans_sst.cfg"):
            staged = source_path / name
            assert staged.stat().st_size > 0
            with real_open(staged, "ab"):
                pass
        atomic_renames.append((source_path, destination_path))
        return real_rename(source, destination, *args, **kwargs)

    def track_builtin_open(path, mode: str = "r", *args, **kwargs):
        ordinary = _ordinary_windows_path(path)
        if mode == "xb" and ordinary.parent.name.endswith(".staging"):
            opened_exclusively.append(ordinary)
        return real_builtin_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", track_open)
    monkeypatch.setattr(builtins, "open", track_builtin_open)
    monkeypatch.setattr(os, "fsync", track_fsync)
    monkeypatch.setattr(os, "rename", track_rename)

    rendered = render_su2_config(
        _case(tmp_path),
        _mesh(tmp_path / "input.su2"),
        _groups(),
        output,
    )

    assert rendered.path == output / "inc_rans_sst.cfg"
    assert len(opened_exclusively) == 2
    assert len({path.parent for path in opened_exclusively}) == 1
    assert all(path.parent.parent == output.parent for path in opened_exclusively)
    assert {path.name for path in opened_exclusively} == {
        "mesh.su2",
        "inc_rans_sst.cfg",
    }
    assert len(synced_descriptors) == 2
    assert atomic_renames == [(opened_exclusively[0].parent, output)]
    assert not list(output.parent.glob(".phoenix-su2-*.staging"))


def test_atomic_directory_commit_collision_preserves_attacker_and_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"
    real_rename = os.rename

    def race_on_commit(source, destination, *args, **kwargs):
        destination_path = _ordinary_windows_path(destination)
        destination_path.mkdir()
        (destination_path / "attacker.txt").write_bytes(b"user raced")
        return real_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", race_on_commit)

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_COLLISION"
    assert (output / "attacker.txt").read_bytes() == b"user raced"
    staging = list(output.parent.glob(".phoenix-su2-*.staging"))
    assert len(staging) == 1
    assert (staging[0] / "mesh.su2").stat().st_size > 0
    assert (staging[0] / "inc_rans_sst.cfg").stat().st_size > 0


def test_atomic_directory_commit_maps_posix_nonempty_collision_consistently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"

    def collide_with_nonempty_directory(*_args, **_kwargs):
        raise OSError(errno.ENOTEMPTY, "destination directory is not empty")

    monkeypatch.setattr(os, "rename", collide_with_nonempty_directory)

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_COLLISION"
    staging = list(output.parent.glob(".phoenix-su2-*.staging"))
    assert len(staging) == 1


def test_second_file_fsync_failure_leaves_isolated_staging_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"
    fsync_calls = 0
    real_fsync = os.fsync

    def fail_second_fsync(descriptor: int):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("injected fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_second_fsync)

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_WRITE_FAILED"
    assert not output.exists()
    staging = list(output.parent.glob(".phoenix-su2-*.staging"))
    assert len(staging) == 1
    assert (staging[0] / "mesh.su2").stat().st_size > 0

    rendered = render_su2_config(
        _case(tmp_path),
        _mesh(tmp_path / "retry.su2"),
        _groups(),
        output,
    )

    assert rendered.path.is_file()
    assert staging[0].is_dir()


def test_staging_creation_failure_has_stable_error_and_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"
    real_mkdir = os.mkdir

    def fail_staging_mkdir(path, *args, **kwargs):
        if _ordinary_windows_path(path).name.endswith(".staging"):
            raise PermissionError("injected staging creation failure")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", fail_staging_mkdir)

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_WRITE_FAILED"
    assert not output.exists()
    assert not list(output.parent.glob(".phoenix-su2-*.staging"))


def test_replaced_staging_on_commit_failure_is_never_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"
    captured = tmp_path / "captured-by-attacker"
    replacement: Path | None = None
    real_rename = os.rename

    def replace_then_fail(source, destination, *args, **kwargs):
        nonlocal replacement
        replacement = _ordinary_windows_path(source)
        real_rename(source, captured, *args, **kwargs)
        replacement.mkdir()
        (replacement / "attacker.txt").write_bytes(b"replacement")
        raise OSError("injected commit failure")

    monkeypatch.setattr(os, "rename", replace_then_fail)

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_WRITE_FAILED"
    assert not output.exists()
    assert replacement is not None
    assert (replacement / "attacker.txt").read_bytes() == b"replacement"
    assert (captured / "mesh.su2").stat().st_size > 0
    assert (captured / "inc_rans_sst.cfg").stat().st_size > 0


def test_baseexception_mid_write_leaves_staging_and_never_creates_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output = tmp_path / "case"
    fsync_calls = 0
    real_fsync = os.fsync

    def interrupt_second_fsync(descriptor: int):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise KeyboardInterrupt
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", interrupt_second_fsync)

    with pytest.raises(KeyboardInterrupt):
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert not output.exists()
    staging = list(output.parent.glob(".phoenix-su2-*.staging"))
    assert len(staging) == 1
    assert (staging[0] / "mesh.su2").stat().st_size > 0


def test_unrelated_crash_staging_does_not_block_a_valid_retry(tmp_path: Path):
    output = tmp_path / "case"
    unrelated = tmp_path / ".phoenix-su2-old-process.staging"
    unrelated.mkdir()
    (unrelated / "do-not-delete.txt").write_bytes(b"do not delete")

    rendered = render_su2_config(
        _case(tmp_path),
        _mesh(tmp_path / "input.su2"),
        _groups(),
        output,
    )

    assert rendered.path.is_file()
    assert (output / "mesh.su2").is_file()
    assert (unrelated / "do-not-delete.txt").read_bytes() == b"do not delete"


def test_atomic_publication_supports_windows_extended_length_paths(
    tmp_path: Path,
):
    segment_length = max(8, 220 - len(str(tmp_path)) - 1)
    output_parent = tmp_path / ("x" * segment_length)
    output = output_parent / "case"
    assert len(str(output)) < 248
    assert (
        len(
            str(
                output_parent
                / (".phoenix-su2-" + "0" * 32 + ".staging")
            )
        )
        >= 248
    )

    rendered = render_su2_config(
        _case(tmp_path),
        _mesh(tmp_path / "input.su2"),
        _groups(),
        output,
    )

    assert rendered.path.is_file()
    assert (output / "mesh.su2").is_file()
    assert not list(output.parent.glob(".phoenix-su2-*.staging"))


def test_relative_mesh_and_output_are_resolved_against_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    source = _mesh(Path("inputs") / "mesh.su2")

    rendered = render_su2_config(
        _case(tmp_path),
        source,
        _groups(),
        Path("outputs") / "case",
    )

    assert rendered.path == (tmp_path / "outputs" / "case" / "inc_rans_sst.cfg")
    assert rendered.path.is_file()


def test_parent_traversal_output_is_rejected_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(working / "input.su2"),
            _groups(),
            Path("..") / "escaped-case",
        )

    assert error.value.code == "SU2_OUTPUT_PATH_UNSAFE"
    assert not (tmp_path / "escaped-case").exists()


def test_redirecting_output_directory_is_rejected_without_touching_target(
    tmp_path: Path,
):
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "case-link"
    try:
        output.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        junction = os.spawnv(
            os.P_WAIT,
            os.environ["COMSPEC"],
            (
                os.environ["COMSPEC"],
                "/c",
                "mklink",
                "/J",
                str(output),
                str(outside),
            ),
        )
        assert junction == 0

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_PATH_UNSAFE"
    assert not list(outside.iterdir())


def test_hardlinked_destination_is_rejected_without_touching_external_file(
    tmp_path: Path,
):
    output = tmp_path / "case"
    output.mkdir()
    outside = tmp_path / "outside.cfg"
    outside.write_bytes(b"outside-original")
    os.link(outside, output / "inc_rans_sst.cfg")

    with pytest.raises(Su2ConfigError) as error:
        render_su2_config(
            _case(tmp_path),
            _mesh(tmp_path / "input.su2"),
            _groups(),
            output,
        )

    assert error.value.code == "SU2_OUTPUT_COLLISION"
    assert outside.read_bytes() == b"outside-original"


def _ordinary_windows_path(path: os.PathLike[str] | str) -> Path:
    native = os.fspath(path)
    if native.startswith("\\\\?\\UNC\\"):
        native = "\\\\" + native[8:]
    elif native.startswith("\\\\?\\"):
        native = native[4:]
    return Path(native)
