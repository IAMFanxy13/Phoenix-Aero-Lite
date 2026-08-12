"""Diagnose the external and bundled Windows runtime without silent fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping

import gmsh


class RuntimeDiscoveryError(ValueError):
    """Stable actionable runtime diagnostic."""


@dataclass(frozen=True, slots=True)
class ToolDiagnostic:
    component: str
    available: bool
    code: str
    version: str | None
    path: Path | None
    message_zh: str


@dataclass(frozen=True, slots=True)
class RuntimeReport:
    su2: ToolDiagnostic
    gmsh: ToolDiagnostic

    @property
    def ready(self) -> bool:
        return self.su2.available and self.gmsh.available


def discover_runtime(
    project_root: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> RuntimeReport:
    """Discover configured SU2 and the imported Gmsh wheel with diagnostics."""

    root = Path(project_root).resolve(strict=False)
    env = dict(os.environ if environment is None else environment)
    config_path = root / "config" / "local_tools.json"
    configured: str | None = None
    if config_path.is_file():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
            value = payload.get("su2_cfd_executable")
            configured = value if isinstance(value, str) and value else None
        except (OSError, json.JSONDecodeError):
            return RuntimeReport(
                _unavailable(
                    "SU2",
                    "SU2_LOCAL_CONFIG_INVALID",
                    "本机 SU2 配置文件无法读取。",
                ),
                _gmsh_diagnostic(),
            )
    path_candidate = (
        shutil.which("SU2_CFD.exe", path=env["PATH"])
        if "PATH" in env
        else None
    )
    candidate = configured or env.get("PAL_SU2_CFD") or path_candidate
    if candidate is None:
        su2 = _unavailable(
            "SU2",
            "SU2_EXECUTABLE_NOT_CONFIGURED",
            "未配置官方 SU2_CFD.exe；不会改用 Fluent 或其他求解器。",
        )
    else:
        try:
            path, version = validate_su2_executable(Path(candidate))
            su2 = ToolDiagnostic(
                "SU2",
                True,
                "OK",
                version,
                path,
                f"已验证官方 SU2 {version}。",
            )
        except RuntimeDiscoveryError as error:
            code = str(error)
            messages = {
                "SU2_EXECUTABLE_MISSING": "SU2_CFD.exe 路径不存在。",
                "SU2_EXECUTABLE_PATH_NOT_ABSOLUTE": "SU2 路径必须是绝对路径。",
                "SU2_EXECUTABLE_NAME_INVALID": "配置文件必须指向 SU2_CFD.exe。",
                "SU2_VERSION_UNSUPPORTED": "需要官方 SU2 8.5.0。",
                "SU2_DLL_MISSING": "SU2 无法启动：缺少 DLL 或 VC++ 运行时。",
                "SU2_LAUNCH_FAILED": "Windows 无法启动 SU2_CFD.exe。",
            }
            su2 = _unavailable("SU2", code, messages.get(code, code))
    return RuntimeReport(su2, _gmsh_diagnostic())


def validate_su2_executable(path: Path) -> tuple[Path, str]:
    """Launch and validate the exact configured official SU2 8.5.0 binary."""

    if not path.is_absolute():
        raise RuntimeDiscoveryError("SU2_EXECUTABLE_PATH_NOT_ABSOLUTE")
    if not path.is_file():
        raise RuntimeDiscoveryError("SU2_EXECUTABLE_MISSING")
    if path.name.casefold() != "su2_cfd.exe":
        raise RuntimeDiscoveryError("SU2_EXECUTABLE_NAME_INVALID")
    resolved = path.resolve(strict=True)
    try:
        result = subprocess.run(
            [str(resolved), "--help"],
            cwd=resolved.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            shell=False,
        )
    except OSError as error:
        if getattr(error, "winerror", None) == 126:
            raise RuntimeDiscoveryError("SU2_DLL_MISSING") from None
        raise RuntimeDiscoveryError("SU2_LAUNCH_FAILED") from None
    except subprocess.TimeoutExpired:
        raise RuntimeDiscoveryError("SU2_LAUNCH_FAILED") from None
    banner = f"{result.stdout}\n{result.stderr}"
    if "8.5.0" not in banner or "SU2" not in banner:
        raise RuntimeDiscoveryError("SU2_VERSION_UNSUPPORTED")
    return resolved, "8.5.0"


def _gmsh_diagnostic() -> ToolDiagnostic:
    version = getattr(gmsh, "__version__", None)
    if version != "4.15.2":
        return _unavailable(
            "Gmsh",
            "GMSH_VERSION_UNSUPPORTED",
            f"需要 Gmsh 4.15.2，当前为 {version or '未知'}。",
        )
    library = Path(getattr(gmsh, "libpath", ""))
    if not library.is_file():
        return _unavailable(
            "Gmsh",
            "GMSH_LIBRARY_MISSING",
            "Gmsh 4.15.2 shared library is missing.",
        )
    return ToolDiagnostic(
        "Gmsh",
        True,
        "OK",
        version,
        library.resolve(strict=True),
        "Gmsh Python/OpenCASCADE 4.15.2 可用。",
    )


def _unavailable(component: str, code: str, message: str) -> ToolDiagnostic:
    return ToolDiagnostic(component, False, code, None, None, message)
