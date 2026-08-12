"""Integration tests for protected, immutable STEP staging."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from phoenix_aero_lite.app.case_workspace import StagedModel, stage_step
from phoenix_aero_lite.utilities.source_guard import SourceValidationError, sha256_file


def test_stage_step_copies_fixture_with_hash_and_source_metadata(
    tmp_path: Path,
):
    source = tmp_path / "external" / "example_model.STEP"
    source.parent.mkdir()
    source.write_bytes(b"ISO-10303-21\nfixture bytes\n")
    source_timestamp_ns = 1_700_000_000_123_456_700
    os.utime(source, ns=(source_timestamp_ns, source_timestamp_ns))
    case_root = tmp_path / "cases" / "case-001"

    staged = stage_step(source, case_root)

    assert isinstance(staged, StagedModel)
    assert staged.source_path == source
    assert staged.staged_path == case_root.resolve() / "input" / "model.step"
    assert staged.sha256 == sha256_file(source)
    assert sha256_file(staged.staged_path) == staged.sha256
    assert staged.staged_path.read_bytes() == source.read_bytes()
    assert staged.staged_path.stat().st_mtime_ns == source.stat().st_mtime_ns
    with pytest.raises(FrozenInstanceError):
        staged.sha256 = "altered"


def test_stage_step_creates_only_paths_under_the_resolved_case_root(tmp_path: Path):
    source = tmp_path / "source.step"
    source.write_bytes(b"fixture")
    case_root = tmp_path / "case" / "nested" / ".." / "workspace"

    staged = stage_step(source, case_root)

    assert staged.staged_path.is_relative_to(case_root.resolve())
    assert {path.relative_to(case_root.resolve()) for path in case_root.resolve().rglob("*")} == {
        Path("input"),
        Path("input/model.step"),
    }


def test_stage_step_rejects_an_input_symlink_that_escapes_the_case_root(
    tmp_path: Path,
):
    source = tmp_path / "source.step"
    source.write_bytes(b"fixture")
    case_root = tmp_path / "case"
    external_root = tmp_path / "outside"
    case_root.mkdir()
    external_root.mkdir()
    input_path = case_root / "input"
    try:
        input_path.symlink_to(external_root, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires unavailable OS privilege")
        raise

    with pytest.raises(ValueError, match="STAGED_MODEL_OUTSIDE_CASE_ROOT"):
        stage_step(source, case_root)

    assert not (external_root / "model.step").exists()


def test_stage_step_refuses_collision_without_overwriting_existing_model(tmp_path: Path):
    source = tmp_path / "source.step"
    source.write_bytes(b"new source")
    staged_path = tmp_path / "case" / "input" / "model.step"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_bytes(b"existing model")

    with pytest.raises(FileExistsError) as error:
        stage_step(source, tmp_path / "case")

    assert error.value.args == (staged_path,)
    assert staged_path.read_bytes() == b"existing model"


def test_stage_step_rejects_sldprt_before_creating_a_case_workspace(tmp_path: Path):
    source = tmp_path / "example_model.SLDPRT"
    source.write_bytes(b"native CAD")
    case_root = tmp_path / "case"

    with pytest.raises(SourceValidationError) as error:
        stage_step(source, case_root)

    assert error.value.issue.code == "MODEL_MUST_BE_STEP"
    assert not case_root.exists()


@pytest.mark.parametrize(
    ("name", "contents", "code"),
    [
        ("missing.step", None, "MODEL_SOURCE_MISSING"),
        ("empty.STP", b"", "MODEL_SOURCE_EMPTY"),
    ],
)
def test_stage_step_rejects_missing_or_empty_inputs_before_creating_case_paths(
    tmp_path: Path, name: str, contents: bytes | None, code: str
):
    source = tmp_path / name
    if contents is not None:
        source.write_bytes(contents)
    case_root = tmp_path / "case"

    with pytest.raises(SourceValidationError) as error:
        stage_step(source, case_root)

    assert error.value.issue.code == code
    assert not case_root.exists()


def test_stage_step_detects_copy_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.step"
    source.write_bytes(b"expected source")

    def copy_corruptly(_: Path, destination: Path) -> Path:
        destination.write_bytes(b"corrupted copy")
        return destination

    monkeypatch.setattr(
        "phoenix_aero_lite.app.case_workspace.shutil.copy2", copy_corruptly
    )

    with pytest.raises(OSError, match="STAGED_MODEL_HASH_MISMATCH"):
        stage_step(source, tmp_path / "case")
