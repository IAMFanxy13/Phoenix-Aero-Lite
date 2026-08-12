"""Project-root discovery independent of a launcher's working directory."""

from __future__ import annotations

from pathlib import Path


def resolve_project_root(
    *, configured_root: str | None, executable_path: Path, cwd: Path
) -> Path:
    if configured_root:
        return Path(configured_root).resolve(strict=False)
    executable = Path(executable_path).resolve(strict=False)
    for candidate in executable.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir():
            return candidate.resolve(strict=True)
    return Path(cwd).resolve(strict=False)
