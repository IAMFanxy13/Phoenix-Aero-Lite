"""Create isolated case-workspace inputs from immutable STEP sources."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from phoenix_aero_lite.utilities.source_guard import sha256_file, validate_step_source


@dataclass(frozen=True, slots=True)
class StagedModel:
    """A verified, immutable model copy owned by a single case workspace."""

    source_path: Path
    staged_path: Path
    sha256: str


def stage_step(source: Path, case_root: Path) -> StagedModel:
    """Copy a validated STEP/STP source into a new case workspace input path."""

    source_path = validate_step_source(source)
    resolved_case_root = Path(case_root).resolve(strict=False)
    staged_path = resolved_case_root / "input" / "model.step"
    _assert_within_case_root(staged_path, resolved_case_root)

    staged_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_within_case_root(staged_path.resolve(strict=False), resolved_case_root)
    if os.path.lexists(staged_path):
        raise FileExistsError(staged_path)

    source_hash = sha256_file(source_path)
    shutil.copy2(source_path, staged_path)
    if sha256_file(staged_path) != source_hash:
        staged_path.unlink(missing_ok=True)
        raise OSError("STAGED_MODEL_HASH_MISMATCH")
    return StagedModel(source_path, staged_path, source_hash)


def _assert_within_case_root(path: Path, resolved_case_root: Path) -> None:
    """Reject symlink traversal that could place staged data outside the case."""

    try:
        path.relative_to(resolved_case_root)
    except ValueError:
        raise ValueError("STAGED_MODEL_OUTSIDE_CASE_ROOT") from None
