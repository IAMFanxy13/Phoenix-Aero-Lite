from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path("scripts/research/write_content_manifest.py").resolve()
MANIFEST_NAME = "content-sha256.json"


def run_manifest(root: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *options, str(root)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


def test_manifest_is_deterministic_sorted_and_excludes_itself(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "z.txt").write_bytes(b"z\n")
    (tmp_path / "nested" / "a.bin").write_bytes(b"abc\x00")

    first = run_manifest(tmp_path)
    first_bytes = (tmp_path / MANIFEST_NAME).read_bytes()
    second = run_manifest(tmp_path)
    second_bytes = (tmp_path / MANIFEST_NAME).read_bytes()
    manifest = json.loads(second_bytes)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first_bytes == second_bytes
    assert manifest == {
        "schema_version": 1,
        "algorithm": "sha256",
        "files": [
            {
                "path": "nested/a.bin",
                "bytes": 4,
                "sha256": hashlib.sha256(b"abc\x00").hexdigest(),
            },
            {
                "path": "z.txt",
                "bytes": 2,
                "sha256": hashlib.sha256(b"z\n").hexdigest(),
            },
        ],
    }
    assert MANIFEST_NAME not in {entry["path"] for entry in manifest["files"]}


def test_manifest_verify_detects_content_changes(tmp_path):
    payload = tmp_path / "payload.txt"
    payload.write_text("original\n", encoding="utf-8")
    assert run_manifest(tmp_path).returncode == 0
    assert run_manifest(tmp_path, "--verify").returncode == 0

    payload.write_text("changed\n", encoding="utf-8")
    verified = run_manifest(tmp_path, "--verify")

    assert verified.returncode == 1
    assert "manifest verification failed" in verified.stderr
