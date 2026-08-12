"""Explicit SU2 semantic-validator dependency contracts."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

import pytest

from phoenix_aero_lite.meshing.gmsh_mesher import GmshMesher
from phoenix_aero_lite.models.mesh import MeshingError


def test_mesher_never_selects_an_unversioned_path_executable(
    tmp_path: Path, monkeypatch
):
    path_binary = tmp_path / "SU2_CFD.exe"
    shutil.copy2(sys.executable, path_binary)
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(MeshingError) as error:
        GmshMesher()

    assert error.value.issue.code == "SU2_VALIDATOR_REQUIRED"
    assert error.value.issue.text_zh


def test_mesher_rejects_a_relative_validator_path():
    with pytest.raises(MeshingError) as error:
        GmshMesher(su2_validator_path=Path("SU2_CFD.exe"))

    assert error.value.issue.code == "SU2_VALIDATOR_PATH_NOT_ABSOLUTE"
    assert error.value.issue.text_zh


def test_mesher_rejects_a_missing_absolute_validator_path(tmp_path: Path):
    with pytest.raises(MeshingError) as error:
        GmshMesher(su2_validator_path=tmp_path / "SU2_CFD.exe")

    assert error.value.issue.code == "SU2_VALIDATOR_NOT_FOUND"
    assert error.value.issue.text_zh


def test_mesher_rejects_a_directory_instead_of_a_validator_file(tmp_path: Path):
    candidate = tmp_path / "SU2_CFD.exe"
    candidate.mkdir()

    with pytest.raises(MeshingError) as error:
        GmshMesher(su2_validator_path=candidate)

    assert error.value.issue.code == "SU2_VALIDATOR_NOT_FOUND"
    assert error.value.issue.text_zh


def test_mesher_rejects_a_wrongly_named_executable(tmp_path: Path):
    candidate = tmp_path / "renamed-validator.exe"
    shutil.copy2(sys.executable, candidate)

    with pytest.raises(MeshingError) as error:
        GmshMesher(su2_validator_path=candidate)

    assert error.value.issue.code == "SU2_VALIDATOR_NAME_INVALID"
    assert error.value.issue.text_zh


def test_mesher_rejects_an_unlaunchable_validator(tmp_path: Path):
    candidate = tmp_path / "SU2_CFD.exe"
    candidate.write_text("not an executable", encoding="utf-8")

    with pytest.raises(MeshingError) as error:
        GmshMesher(su2_validator_path=candidate)

    assert error.value.issue.code == "SU2_VALIDATOR_LAUNCH_FAILED"
    assert error.value.issue.text_zh


def test_mesher_rejects_a_launchable_wrong_version_validator(tmp_path: Path):
    candidate = tmp_path / "SU2_CFD.exe"
    shutil.copy2(sys.executable, candidate)

    with pytest.raises(MeshingError) as error:
        GmshMesher(su2_validator_path=candidate)

    assert error.value.issue.code == "SU2_VALIDATOR_VERSION_UNSUPPORTED"
    assert error.value.issue.text_zh
