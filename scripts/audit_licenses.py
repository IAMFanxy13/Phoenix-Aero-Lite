"""Fail when a declared runtime dependency lacks a recorded notice."""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
import sys
import tomllib


ALIASES = {
    "fastapi": "FastAPI",
    "jinja2": "Jinja2",
    "matplotlib": "Matplotlib",
    "packaging": "packaging",
    "pandas": "pandas",
    "psutil": "psutil",
    "pyside6": "PySide6",
    "pyvista": "PyVista",
    "pyvistaqt": "PyVistaQt",
    "meshio": "meshio",
    "gmsh": "Gmsh",
    "trame": "Trame",
    "uvicorn": "Uvicorn",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    dependencies = project["project"]["dependencies"]
    records = []
    failures = []
    for requirement in dependencies:
        normalized = requirement.split("==", 1)[0].strip().casefold()
        display = ALIASES.get(normalized, normalized)
        expected = requirement.split("==", 1)[1] if "==" in requirement else None
        try:
            installed = metadata.version(normalized)
        except metadata.PackageNotFoundError:
            installed = None
        recorded = f"| {display} " in notices or f"| {display} /" in notices
        records.append(
            {
                "dependency": normalized,
                "expected": expected,
                "installed": installed,
                "notice_recorded": recorded,
            }
        )
        if not recorded:
            failures.append(f"{normalized}: no THIRD_PARTY_NOTICES entry")
        if installed is not None and expected is not None and installed != expected:
            failures.append(
                f"{normalized}: installed {installed}, expected {expected}"
            )
    print(json.dumps(records, ensure_ascii=False, indent=2))
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
