"""Tests for validating and hashing immutable source CAD files."""

from __future__ import annotations

from pathlib import Path

import pytest

from phoenix_aero_lite.utilities.source_guard import (
    SourceValidationError,
    sha256_file,
    validate_step_source,
)


def test_validate_step_source_accepts_step_and_stp_files(tmp_path: Path):
    step = tmp_path / "airframe.STEP"
    stp = tmp_path / "airframe.stp"
    step.write_bytes(b"STEP fixture")
    stp.write_bytes(b"STP fixture")

    assert validate_step_source(step) == step
    assert validate_step_source(stp) == stp


@pytest.mark.parametrize(
    ("name", "contents", "code"),
    [
        ("airframe.SLDPRT", b"native CAD", "MODEL_MUST_BE_STEP"),
        ("missing.step", None, "MODEL_SOURCE_MISSING"),
        ("empty.step", b"", "MODEL_SOURCE_EMPTY"),
    ],
)
def test_validate_step_source_returns_stable_chinese_issue(
    tmp_path: Path, name: str, contents: bytes | None, code: str
):
    source = tmp_path / name
    if contents is not None:
        source.write_bytes(contents)

    with pytest.raises(SourceValidationError) as error:
        validate_step_source(source)

    assert error.value.issue.code == code
    assert error.value.issue.text_zh
    assert error.value.issues == (error.value.issue,)


def test_sha256_file_hashes_large_input_without_reading_all_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "large.step"
    source.write_bytes((b"0123456789abcdef" * 131_072) + b"tail")

    def read_bytes_is_not_allowed(_: Path) -> bytes:
        raise AssertionError("large files must be streamed")

    monkeypatch.setattr(Path, "read_bytes", read_bytes_is_not_allowed)

    assert sha256_file(source, chunk_size=64 * 1024) == (
        "dfef245e869121b2d3a5220b54320a9785d62b14cd39e0060ae6a9a6a5efe74a"
    )
