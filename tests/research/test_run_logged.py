from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time


RUNNER = Path("scripts/research/run_logged.py").resolve()


def run_logged(tmp_path: Path, validation_id: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--id",
            validation_id,
            "--root",
            str(tmp_path),
            "--cwd",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            "print('new output')",
        ],
        check=False,
    )


def test_runner_records_output_and_nonzero_exit(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--id",
            "sample",
            "--root",
            str(tmp_path),
            "--cwd",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)",
        ],
        check=False,
    )

    evidence = tmp_path / "sample"
    metadata = json.loads((evidence / "metadata.json").read_text(encoding="utf-8"))
    assert completed.returncode == 3
    assert metadata["exit_code"] == 3
    assert (evidence / "stdout.txt").read_text(encoding="utf-8") == "out\n"
    assert (evidence / "stderr.txt").read_text(encoding="utf-8") == "err\n"


def test_runner_records_missing_executable_as_127(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--id",
            "missing",
            "--root",
            str(tmp_path),
            "--cwd",
            str(tmp_path),
            "--",
            "executable-that-does-not-exist.exe",
        ],
        check=False,
    )

    metadata = json.loads(
        (tmp_path / "missing" / "metadata.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 127
    assert metadata["exit_code"] == 127
    assert metadata["launch_state"] == "not_found"
    assert "FileNotFoundError" in (tmp_path / "missing" / "stderr.txt").read_text(
        encoding="utf-8"
    )


def test_runner_rejects_id_that_can_escape_evidence_root(tmp_path):
    completed = run_logged(tmp_path, "../escape")

    assert completed.returncode == 2
    assert not (tmp_path.parent / "escape").exists()


def test_runner_refuses_to_overwrite_existing_evidence(tmp_path):
    evidence = tmp_path / "existing"
    evidence.mkdir()
    metadata = evidence / "metadata.json"
    metadata.write_text('{"original": true}\n', encoding="utf-8")

    completed = run_logged(tmp_path, "existing")

    assert completed.returncode == 2
    assert metadata.read_text(encoding="utf-8") == '{"original": true}\n'
    assert not (evidence / "stdout.txt").exists()


def test_runner_refuses_preexisting_directory_containing_only_work(tmp_path):
    evidence = tmp_path / "stale"
    work = evidence / "work"
    work.mkdir(parents=True)
    marker = work / "keep.txt"
    marker.write_text("stale\n", encoding="utf-8")

    completed = run_logged(tmp_path, "stale")

    assert completed.returncode == 2
    assert marker.read_text(encoding="utf-8") == "stale\n"
    assert not (evidence / "metadata.json").exists()


def test_runner_exclusively_reserves_target_against_concurrent_run(tmp_path):
    command = [
        sys.executable,
        str(RUNNER),
        "--id",
        "concurrent",
        "--root",
        str(tmp_path),
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(0.5); print('owner')",
    ]
    owner = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 2.0
    while not (tmp_path / "concurrent").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    contender = subprocess.run(command, capture_output=True, check=False)
    owner_stdout, owner_stderr = owner.communicate(timeout=10)

    assert owner.returncode == 0, (owner_stdout, owner_stderr)
    assert contender.returncode == 2
    assert (tmp_path / "concurrent" / "stdout.txt").read_text(
        encoding="utf-8"
    ) == "owner\n"


def test_runner_records_launch_oserror_as_complete_evidence(tmp_path):
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("not a Windows executable\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--id",
            "launch-error",
            "--root",
            str(tmp_path),
            "--cwd",
            str(tmp_path),
            "--",
            str(not_executable),
        ],
        capture_output=True,
        check=False,
    )

    evidence = tmp_path / "launch-error"
    metadata = json.loads((evidence / "metadata.json").read_text(encoding="utf-8"))
    assert completed.returncode == 126
    assert metadata["exit_code"] == 126
    assert metadata["launch_state"] == "launch_failed"
    assert metadata["exception_type"] in {"OSError", "PermissionError"}
    assert metadata["exception_message"]
    assert set(path.name for path in evidence.iterdir()) == {
        "command.txt",
        "metadata.json",
        "stdout.txt",
        "stderr.txt",
    }
    assert metadata["exception_type"] in (evidence / "stderr.txt").read_text(
        encoding="utf-8"
    )
