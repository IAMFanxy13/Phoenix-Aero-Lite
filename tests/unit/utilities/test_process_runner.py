from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from phoenix_aero_lite.utilities.process_runner import (
    CancellationToken,
    ProcessRunnerError,
    ProcessStatus,
    run_process,
)


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "processes"
    / "emit_output.py"
)


def _argv(*items: str) -> list[str]:
    return [sys.executable, str(FIXTURE), *items]


def test_separates_logs_callbacks_and_audit_metadata(tmp_path: Path):
    stdout_events: list[str] = []
    stderr_events: list[str] = []
    result = run_process(
        _argv("--stdout", "你好\n", "--stderr", "错误\n"),
        cwd=tmp_path,
        audit_directory=tmp_path / "audit",
        environment_delta={"PAL_TEST": "yes"},
        on_stdout=stdout_events.append,
        on_stderr=stderr_events.append,
    )

    assert result.status is ProcessStatus.SUCCEEDED
    assert result.exit_code == 0
    assert result.argv == tuple(_argv("--stdout", "你好\n", "--stderr", "错误\n"))
    assert result.cwd == tmp_path.resolve()
    assert dict(result.environment_delta) == {"PAL_TEST": "yes"}
    assert result.stdout_path.read_bytes() == "你好\n".encode()
    assert result.stderr_path.read_bytes() == "错误\n".encode()
    assert "".join(stdout_events) == "你好\n"
    assert "".join(stderr_events) == "错误\n"
    assert result.ended_at >= result.started_at


def test_nonzero_timeout_start_failure_and_precancel_are_distinct(tmp_path: Path):
    nonzero = run_process(
        _argv("--exit-code", "7"),
        cwd=tmp_path,
        audit_directory=tmp_path / "nonzero",
    )
    assert (nonzero.status, nonzero.exit_code) == (ProcessStatus.NONZERO_EXIT, 7)

    timed_out = run_process(
        _argv("--delay", "2", "--stdout", "x"),
        cwd=tmp_path,
        audit_directory=tmp_path / "timeout",
        timeout_s=0.1,
        termination_grace_s=0.05,
    )
    assert timed_out.status is ProcessStatus.TIMED_OUT

    missing = tmp_path / "missing.exe"
    failed = run_process(
        [str(missing)],
        cwd=tmp_path,
        audit_directory=tmp_path / "start-failed",
    )
    assert failed.status is ProcessStatus.START_FAILED
    assert failed.exit_code is None

    token = CancellationToken()
    token.cancel()
    cancelled = run_process(
        _argv("--stdout", "must-not-run"),
        cwd=tmp_path,
        audit_directory=tmp_path / "cancelled",
        cancellation=token,
    )
    assert cancelled.status is ProcessStatus.CANCELLED
    assert cancelled.stdout_path.read_bytes() == b""


def test_cancel_kills_owned_tree_but_not_unrelated_process(tmp_path: Path):
    token = CancellationToken()
    stdout: list[str] = []
    unrelated = psutil.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(30)"]
    )
    holder: dict[str, object] = {}

    def invoke() -> None:
        holder["result"] = run_process(
            _argv("--spawn-child"),
            cwd=tmp_path,
            audit_directory=tmp_path / "cancel-tree",
            cancellation=token,
            on_stdout=stdout.append,
            termination_grace_s=0.05,
        )

    thread = threading.Thread(target=invoke)
    thread.start()
    deadline = time.monotonic() + 5
    while "CHILD_PID=" not in "".join(stdout) and time.monotonic() < deadline:
        time.sleep(0.01)
    child_pid = int("".join(stdout).split("CHILD_PID=", 1)[1].splitlines()[0])
    token.cancel()
    thread.join(5)

    try:
        assert holder["result"].status is ProcessStatus.CANCELLED
        deadline = time.monotonic() + 3
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not psutil.pid_exists(child_pid)
        assert unrelated.is_running()
    finally:
        unrelated.kill()
        unrelated.wait()


@pytest.mark.parametrize(
    "argv",
    ["echo unsafe", [], ["relative-program"], [sys.executable, 3], [sys.executable, "a\0b"]],
)
def test_rejects_unsafe_argv_without_shell(tmp_path: Path, argv):
    with pytest.raises(ProcessRunnerError):
        run_process(argv, cwd=tmp_path, audit_directory=tmp_path / "audit")


def test_existing_logs_and_parent_environment_are_not_overwritten(tmp_path: Path):
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "stdout.bin").write_bytes(b"keep")
    with pytest.raises(ProcessRunnerError, match="PROCESS_LOG_COLLISION"):
        run_process(_argv(), cwd=tmp_path, audit_directory=audit)
    assert (audit / "stdout.bin").read_bytes() == b"keep"


def test_callback_failure_does_not_lose_process_output(tmp_path: Path):
    def broken(_: str) -> None:
        raise RuntimeError("consumer failed")

    result = run_process(
        _argv("--stdout", "preserved"),
        cwd=tmp_path,
        audit_directory=tmp_path / "audit",
        on_stdout=broken,
    )
    assert result.status is ProcessStatus.SUCCEEDED
    assert result.stdout_path.read_bytes() == b"preserved"
