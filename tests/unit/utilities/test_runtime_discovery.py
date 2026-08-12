from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import gmsh

from phoenix_aero_lite.utilities.runtime_discovery import (
    RuntimeDiscoveryError,
    _gmsh_diagnostic,
    discover_runtime,
    validate_su2_executable,
)


def test_explicit_local_config_path_with_spaces_is_selected(monkeypatch, tmp_path: Path):
    executable = tmp_path / "Tools With Spaces" / "SU2_CFD.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"MZ fixture")
    config = tmp_path / "config" / "local_tools.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"su2_cfd_executable": str(executable)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "phoenix_aero_lite.utilities.runtime_discovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="SU2 8.5.0 Harrier",
            stderr="",
        ),
    )
    report = discover_runtime(tmp_path)
    assert report.ready
    assert report.su2.path == executable.resolve()
    assert report.su2.version == "8.5.0"


def test_powershell_utf8_bom_local_config_is_accepted(monkeypatch, tmp_path: Path):
    executable = tmp_path / "SU2_CFD.exe"
    executable.write_bytes(b"MZ fixture")
    config = tmp_path / "config" / "local_tools.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"su2_cfd_executable": str(executable)}),
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(
        "phoenix_aero_lite.utilities.runtime_discovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="SU2 8.5.0 Harrier",
            stderr="",
        ),
    )
    assert discover_runtime(tmp_path).ready


def test_missing_wrong_version_and_missing_dll_have_distinct_diagnostics(
    monkeypatch, tmp_path: Path
):
    with pytest.raises(RuntimeDiscoveryError, match="SU2_EXECUTABLE_MISSING"):
        validate_su2_executable(tmp_path / "SU2_CFD.exe")
    executable = tmp_path / "SU2_CFD.exe"
    executable.write_bytes(b"MZ")
    monkeypatch.setattr(
        "phoenix_aero_lite.utilities.runtime_discovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="SU2 7.5.0", stderr=""
        ),
    )
    with pytest.raises(RuntimeDiscoveryError, match="SU2_VERSION_UNSUPPORTED"):
        validate_su2_executable(executable)

    def missing_dll(*_args, **_kwargs):
        error = OSError("missing runtime")
        error.winerror = 126
        raise error

    monkeypatch.setattr(
        "phoenix_aero_lite.utilities.runtime_discovery.subprocess.run",
        missing_dll,
    )
    with pytest.raises(RuntimeDiscoveryError, match="SU2_DLL_MISSING"):
        validate_su2_executable(executable)


def test_never_silently_substitutes_fluent(tmp_path: Path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "local_tools.json").write_text(
        json.dumps({"fluent_executable": "C:/ANSYS/fluent.exe"}),
        encoding="utf-8",
    )
    report = discover_runtime(tmp_path, environment={})
    assert not report.ready
    assert report.su2.code == "SU2_EXECUTABLE_NOT_CONFIGURED"


def test_user_path_is_supported_without_any_solver_fallback(
    tmp_path: Path, monkeypatch
):
    executable = tmp_path / "SU2_CFD.exe"
    executable.write_bytes(b"MZ")
    monkeypatch.setattr(
        "phoenix_aero_lite.utilities.runtime_discovery.shutil.which",
        lambda name, path=None: str(executable) if name == "SU2_CFD.exe" else None,
    )
    monkeypatch.setattr(
        "phoenix_aero_lite.utilities.runtime_discovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="SU2 8.5.0 Harrier", stderr=""
        ),
    )
    report = discover_runtime(tmp_path, environment={"PATH": str(tmp_path)})
    assert report.ready
    assert report.su2.path == executable.resolve()


def test_frozen_gmsh_uses_real_shared_library_not_virtual_module_path(
    tmp_path: Path, monkeypatch
):
    shared_library = tmp_path / "gmsh-4.15.dll"
    shared_library.write_bytes(b"MZ fixture")
    monkeypatch.setattr(gmsh, "__file__", str(tmp_path / "virtual" / "gmsh.py"))
    monkeypatch.setattr(gmsh, "libpath", str(shared_library))

    diagnostic = _gmsh_diagnostic()

    assert diagnostic.available
    assert diagnostic.path == shared_library.resolve()
