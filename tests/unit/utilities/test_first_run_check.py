from __future__ import annotations

import os
import socket
from pathlib import Path

from phoenix_aero_lite.utilities.first_run_check import run_first_run_checks
from phoenix_aero_lite.utilities.runtime_discovery import (
    RuntimeReport,
    ToolDiagnostic,
)


def _runtime(*, ready: bool) -> RuntimeReport:
    return RuntimeReport(
        su2=ToolDiagnostic(
            "SU2",
            ready,
            "OK" if ready else "SU2_EXECUTABLE_MISSING",
            "8.5.0" if ready else None,
            Path("C:/Tools/SU2_CFD.exe") if ready else None,
            "SU2 可用。" if ready else "SU2 不可用。",
        ),
        gmsh=ToolDiagnostic(
            "Gmsh",
            True,
            "OK",
            "4.15.2",
            Path("C:/Python/gmsh.dll"),
            "Gmsh 可用。",
        ),
    )


def test_first_run_report_covers_resources_paths_tools_and_port(tmp_path: Path):
    report = run_first_run_checks(
        tmp_path,
        port=0,
        runtime_report=_runtime(ready=True),
    )

    codes = {check.code for check in report.checks}
    assert {
        "WINDOWS_VERSION",
        "PYTHON_VERSION",
        "CPU_AVAILABLE",
        "RAM_AVAILABLE",
        "DISK_SPACE",
        "PROJECT_WRITABLE",
        "UNICODE_PATH",
        "LONG_PATH_RISK",
        "BROWSER_AVAILABLE",
        "PORT_AVAILABLE",
        "GMSH_RUNTIME",
        "SU2_RUNTIME",
        "PYTHON_PACKAGES",
    } <= codes
    windows_check = next(check for check in report.checks if check.code == "WINDOWS_VERSION")
    assert report.ready is (os.name == "nt")
    assert windows_check.status == ("pass" if os.name == "nt" else "blocker")


def test_occupied_port_and_missing_su2_are_actionable_without_leaking_paths(
    tmp_path: Path,
):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        report = run_first_run_checks(
            tmp_path / "含中文",
            port=port,
            runtime_report=_runtime(ready=False),
        )
    finally:
        listener.close()

    by_code = {check.code: check for check in report.checks}
    assert report.ready is False
    assert by_code["PORT_AVAILABLE"].status == "blocker"
    assert "端口" in by_code["PORT_AVAILABLE"].remediation_zh
    assert by_code["SU2_RUNTIME"].status == "blocker"
    assert "SU2" in by_code["SU2_RUNTIME"].remediation_zh

    public = report.to_public_dict()
    rendered = str(public)
    assert str(tmp_path) not in rendered
    assert "C:/Tools/SU2_CFD.exe" not in rendered
    assert public["ready"] is False


def test_port_zero_is_treated_as_an_ephemeral_available_port(tmp_path: Path):
    report = run_first_run_checks(
        tmp_path,
        port=0,
        runtime_report=_runtime(ready=True),
    )

    port_check = next(check for check in report.checks if check.code == "PORT_AVAILABLE")
    assert port_check.status == "pass"
