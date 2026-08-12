# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for an internal/evaluation Windows build."""

from pathlib import Path

import gmsh

project_root = Path(SPECPATH).parent
datas = [
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
    (
        str(project_root / "docs" / "research" / "upstream_versions.md"),
        "docs/research",
    ),
    (
        str(project_root / "src" / "phoenix_aero_lite" / "templates"),
        "phoenix_aero_lite/templates",
    ),
]
binaries = [(str(Path(gmsh.__file__).parents[1] / "gmsh-4.15.dll"), ".")]
hiddenimports = ["gmsh", "pyvista", "pyvistaqt"]

analysis = Analysis(
    [str(project_root / "src" / "phoenix_aero_lite" / "app" / "gui.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # These tools are installed only for development.  If mypy is partially
    # collected, PyVista's optional plugin detects it at runtime and imports a
    # hashed mypyc extension that PyInstaller cannot resolve.
    excludes=["mypy", "pytest", "py"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PhoenixAeroLite",
    console=False,
    disable_windowed_traceback=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="PhoenixAeroLite",
)
