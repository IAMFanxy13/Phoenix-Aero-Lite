from importlib.metadata import PackageNotFoundError

import phoenix_aero_lite.utilities.environment as environment


def test_collect_environment_reports_local_tools_packages_and_resources(monkeypatch):
    locations = {
        "gmsh": r"C:\Tools\gmsh.exe",
        "SU2_CFD.exe": r"C:\Tools\SU2_CFD.exe",
    }
    versions = {"pyvista": "0.48.4"}

    monkeypatch.setattr(environment.shutil, "which", locations.get)
    monkeypatch.setattr(
        environment.metadata,
        "version",
        lambda package: versions[package],
    )
    monkeypatch.setattr(environment.psutil, "cpu_count", lambda logical: 12)
    monkeypatch.setattr(
        environment.psutil,
        "virtual_memory",
        lambda: type("Memory", (), {"total": 32 * 1024**3})(),
    )

    report = environment.collect_environment()

    assert report.python_version
    assert report.gmsh_path == r"C:\Tools\gmsh.exe"
    assert report.su2_cfd_path == r"C:\Tools\SU2_CFD.exe"
    assert report.pyvista_version == "0.48.4"
    assert report.cpu_count == 12
    assert report.memory_total_bytes == 32 * 1024**3


def test_collect_environment_marks_missing_package_version(monkeypatch):
    monkeypatch.setattr(environment.shutil, "which", lambda command: None)

    def missing_version(package: str) -> str:
        raise PackageNotFoundError(package)

    monkeypatch.setattr(environment.metadata, "version", missing_version)
    monkeypatch.setattr(environment.psutil, "cpu_count", lambda logical: None)
    monkeypatch.setattr(
        environment.psutil,
        "virtual_memory",
        lambda: type("Memory", (), {"total": 0})(),
    )

    report = environment.collect_environment()

    assert report.gmsh_path is None
    assert report.su2_cfd_path is None
    assert report.pyvista_version is None
    assert report.cpu_count is None
    assert report.memory_total_bytes == 0


def test_format_environment_report_includes_required_diagnostics():
    report = environment.EnvironmentReport(
        python_version="3.12.0",
        gmsh_path=r"C:\Tools\gmsh.exe",
        su2_cfd_path=None,
        pyvista_version="0.48.4",
        cpu_count=12,
        memory_total_bytes=32 * 1024**3,
    )

    lines = environment.format_environment_report(report)

    assert lines == (
        "Python: 3.12.0",
        r"Gmsh: C:\Tools\gmsh.exe",
        "SU2: not found",
        "PyVista: 0.48.4",
        "CPU: 12",
        "RAM: 32.0 GiB",
    )
