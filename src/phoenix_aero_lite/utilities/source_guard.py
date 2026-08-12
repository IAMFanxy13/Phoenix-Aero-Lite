"""Validation and streaming hashes for immutable STEP source files."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from phoenix_aero_lite.models.errors import ValidationIssue


_STEP_SUFFIXES = frozenset({".step", ".stp"})
_HASH_CHUNK_SIZE = 1024 * 1024
_SOURCE_ISSUE_TEXT_ZH = {
    "MODEL_MUST_BE_STEP": "模型文件必须为 STEP 或 STP 格式。",
    "MODEL_SOURCE_MISSING": "模型源文件不存在或不是常规文件。",
    "MODEL_SOURCE_EMPTY": "模型源文件不能为空。",
}


class SourceValidationError(ValueError):
    """Raised when a CAD source cannot cross the STEP staging boundary."""

    def __init__(self, code: str) -> None:
        self.issue = ValidationIssue(code=code, text_zh=_SOURCE_ISSUE_TEXT_ZH[code])
        self.issues = (self.issue,)
        super().__init__(self.issue.code)


def validate_step_source(source: Path) -> Path:
    """Return a non-empty STEP/STP file or raise a stable domain error."""

    source_path = Path(source)
    if source_path.suffix.lower() not in _STEP_SUFFIXES:
        raise SourceValidationError("MODEL_MUST_BE_STEP")
    if not source_path.is_file():
        raise SourceValidationError("MODEL_SOURCE_MISSING")
    if source_path.stat().st_size == 0:
        raise SourceValidationError("MODEL_SOURCE_EMPTY")
    return source_path


def sha256_file(path: Path, *, chunk_size: int = _HASH_CHUNK_SIZE) -> str:
    """Stream a file into SHA-256 without materializing its bytes in memory."""

    digest = sha256()
    with Path(path).open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
