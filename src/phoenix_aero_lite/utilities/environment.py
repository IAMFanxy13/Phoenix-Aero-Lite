"""Read-only local environment diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import platform
import shutil

import psutil


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    """Versions, executable locations, and workstation resources."""

    python_version: str
    gmsh_path: str | None
    su2_cfd_path: str | None
    pyvista_version: str | None
    cpu_count: int | None
    memory_total_bytes: int


def collect_environment() -> EnvironmentReport:
    """Collect diagnostics without installing tools or changing the environment."""
    return EnvironmentReport(
        python_version=platform.python_version(),
        gmsh_path=shutil.which("gmsh"),
        su2_cfd_path=shutil.which("SU2_CFD.exe"),
        pyvista_version=_package_version("pyvista"),
        cpu_count=psutil.cpu_count(logical=True),
        memory_total_bytes=psutil.virtual_memory().total,
    )


def format_environment_report(report: EnvironmentReport) -> tuple[str, ...]:
    """Return human-readable diagnostics for the command-line interface."""
    return (
        f"Python: {report.python_version}",
        f"Gmsh: {report.gmsh_path or 'not found'}",
        f"SU2: {report.su2_cfd_path or 'not found'}",
        f"PyVista: {report.pyvista_version or 'not found'}",
        f"CPU: {report.cpu_count if report.cpu_count is not None else 'not found'}",
        f"RAM: {report.memory_total_bytes / 1024**3:.1f} GiB",
    )


def _package_version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None
