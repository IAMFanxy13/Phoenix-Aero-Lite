"""Read-only first-run checks with actionable Chinese diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import os
from pathlib import Path
import platform
import shutil
import socket
import sys
import tempfile
from typing import Literal

import psutil

from phoenix_aero_lite.utilities.runtime_discovery import (
    RuntimeReport,
    discover_runtime,
)


CheckStatus = Literal["pass", "warning", "blocker"]


@dataclass(frozen=True, slots=True)
class FirstRunCheck:
    code: str
    label_zh: str
    status: CheckStatus
    summary_zh: str
    remediation_zh: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "label_zh": self.label_zh,
            "status": self.status,
            "summary_zh": self.summary_zh,
            "remediation_zh": self.remediation_zh,
        }


@dataclass(frozen=True, slots=True)
class FirstRunReport:
    checks: tuple[FirstRunCheck, ...]

    @property
    def ready(self) -> bool:
        return not any(check.status == "blocker" for check in self.checks)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "checks": [check.to_public_dict() for check in self.checks],
        }


_REQUIRED_PACKAGES = (
    "fastapi",
    "gmsh",
    "jinja2",
    "meshio",
    "numpy",
    "pandas",
    "psutil",
    "pyvista",
    "trame",
    "uvicorn",
)


def run_first_run_checks(
    project_root: Path,
    *,
    port: int = 8011,
    runtime_report: RuntimeReport | None = None,
) -> FirstRunReport:
    """Inspect the local workstation without installing or changing tools."""

    root = Path(project_root).resolve(strict=False)
    runtime = runtime_report or discover_runtime(root)
    checks = [
        _windows_check(),
        _python_check(),
        _cpu_check(),
        _ram_check(),
        _disk_check(root),
        _writable_check(root),
        _unicode_path_check(root),
        _long_path_check(root),
        _browser_check(),
        _port_check(port),
        _tool_check("GMSH_RUNTIME", runtime.gmsh),
        _tool_check("SU2_RUNTIME", runtime.su2),
        _package_check(),
    ]
    return FirstRunReport(tuple(checks))


def _check(
    code: str,
    label: str,
    status: CheckStatus,
    summary: str,
    remediation: str = "无需操作。",
) -> FirstRunCheck:
    return FirstRunCheck(code, label, status, summary, remediation)


def _windows_check() -> FirstRunCheck:
    if os.name != "nt":
        return _check(
            "WINDOWS_VERSION",
            "Windows",
            "blocker",
            f"当前系统为 {platform.system() or '未知'}，正式桌面流程仅验证 Windows。",
            "请在 64 位 Windows 10 或 Windows 11 上运行。",
        )
    release = platform.release() or "未知版本"
    return _check("WINDOWS_VERSION", "Windows", "pass", f"Windows {release} 可用。")


def _python_check() -> FirstRunCheck:
    version = platform.python_version()
    if sys.version_info[:2] != (3, 12):
        return _check(
            "PYTHON_VERSION",
            "Python",
            "blocker",
            f"当前 Python {version}，项目固定使用 3.12。",
            "请运行双击启动脚本，让它使用项目的 Python 3.12 虚拟环境。",
        )
    return _check("PYTHON_VERSION", "Python", "pass", f"Python {version} 可用。")


def _cpu_check() -> FirstRunCheck:
    count = psutil.cpu_count(logical=True) or 0
    status: CheckStatus = "pass" if count >= 4 else "warning"
    return _check(
        "CPU_AVAILABLE",
        "CPU",
        status,
        f"检测到 {count} 个逻辑处理器。",
        "少于 4 个逻辑处理器时建议先使用几何检查或初步趋势预设。",
    )


def _ram_check() -> FirstRunCheck:
    gib = psutil.virtual_memory().total / 1024**3
    status: CheckStatus = "pass" if gib >= 8 else "warning"
    return _check(
        "RAM_AVAILABLE",
        "内存",
        status,
        f"物理内存约 {gib:.1f} GiB。",
        "低于 8 GiB 时请关闭大型应用并避免细网格或密集流线。",
    )


def _disk_check(root: Path) -> FirstRunCheck:
    anchor = _existing_parent(root)
    try:
        free_gib = shutil.disk_usage(anchor).free / 1024**3
    except OSError:
        return _check(
            "DISK_SPACE",
            "磁盘空间",
            "blocker",
            "无法读取项目所在磁盘的剩余空间。",
            "确认项目磁盘在线且当前用户可以访问。",
        )
    status: CheckStatus = "pass" if free_gib >= 10 else "warning"
    return _check(
        "DISK_SPACE",
        "磁盘空间",
        status,
        f"项目磁盘剩余约 {free_gib:.1f} GiB。",
        "建议至少保留 10 GiB；细网格和流场文件可能占用大量空间。",
    )


def _writable_check(root: Path) -> FirstRunCheck:
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="pal-check-", dir=root, delete=True):
            pass
    except OSError:
        return _check(
            "PROJECT_WRITABLE",
            "写入权限",
            "blocker",
            "项目数据目录不可写。",
            "把项目放到当前用户可写目录，并避免受保护的 Program Files 目录。",
        )
    return _check("PROJECT_WRITABLE", "写入权限", "pass", "项目数据目录可写。")


def _unicode_path_check(root: Path) -> FirstRunCheck:
    contains_unicode = any(ord(character) > 127 for character in str(root))
    if contains_unicode:
        return _check(
            "UNICODE_PATH",
            "中文路径",
            "warning",
            "项目路径包含非 ASCII 字符；Python 可读取，但外部 CFD 工具兼容性需留意。",
            "若 Gmsh 或 SU2 报路径错误，请把计算目录迁移到较短的纯英文路径。",
        )
    return _check("UNICODE_PATH", "中文路径", "pass", "项目路径为 ASCII 字符。")


def _long_path_check(root: Path) -> FirstRunCheck:
    length = len(str(root))
    if length > 180:
        return _check(
            "LONG_PATH_RISK",
            "长路径",
            "warning",
            f"项目根路径长度为 {length} 个字符，任务子目录可能接近 Windows 限制。",
            "建议使用较短项目路径，或在 Windows 中启用长路径支持。",
        )
    return _check("LONG_PATH_RISK", "长路径", "pass", f"项目根路径长度为 {length} 个字符。")


def _browser_check() -> FirstRunCheck:
    candidates = ("msedge.exe", "chrome.exe", "firefox.exe")
    if any(shutil.which(name) for name in candidates):
        return _check("BROWSER_AVAILABLE", "浏览器", "pass", "检测到可用的现代浏览器。")
    return _check(
        "BROWSER_AVAILABLE",
        "浏览器",
        "warning",
        "PATH 中未检测到 Edge、Chrome 或 Firefox。",
        "可手动在现代浏览器中打开启动器显示的本机地址。",
    )


def _port_check(port: int) -> FirstRunCheck:
    if port == 0:
        return _check("PORT_AVAILABLE", "本机端口", "pass", "将使用系统分配的临时端口。")
    if not 1 <= port <= 65535:
        return _check(
            "PORT_AVAILABLE",
            "本机端口",
            "blocker",
            "端口号超出有效范围。",
            "请选择 1 到 65535 之间的本机端口。",
        )
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        return _check(
            "PORT_AVAILABLE",
            "本机端口",
            "blocker",
            f"本机端口 {port} 已被占用。",
            "关闭占用该端口的旧 Phoenix 进程，或在启动器中选择其他端口。",
        )
    finally:
        probe.close()
    return _check("PORT_AVAILABLE", "本机端口", "pass", f"本机端口 {port} 可用。")


def _tool_check(code: str, diagnostic) -> FirstRunCheck:
    if diagnostic.available:
        return _check(code, diagnostic.component, "pass", diagnostic.message_zh)
    return _check(
        code,
        diagnostic.component,
        "blocker",
        diagnostic.message_zh,
        f"按安装文档配置受支持的 {diagnostic.component}，然后重新运行环境自检。",
    )


def _package_check() -> FirstRunCheck:
    missing = []
    for package in _REQUIRED_PACKAGES:
        try:
            metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)
    if missing:
        return _check(
            "PYTHON_PACKAGES",
            "Python 依赖",
            "blocker",
            "缺少必要依赖：" + "、".join(missing) + "。",
            "运行项目依赖安装脚本，不要从未知来源下载单独 DLL。",
        )
    return _check("PYTHON_PACKAGES", "Python 依赖", "pass", "必要 Python 依赖已安装。")


def _existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate
