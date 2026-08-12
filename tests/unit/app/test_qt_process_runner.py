from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from phoenix_aero_lite.app.qt_process_runner import QtProcessRunner
from phoenix_aero_lite.utilities.process_runner import ProcessStatus


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "processes"
    / "emit_output.py"
)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _run(runner: QtProcessRunner, timeout_ms: int = 5000):
    _app()
    loop = QEventLoop()
    results: list[object] = []
    runner.completed.connect(results.append)
    runner.completed.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert results
    return results[0]


def test_qprocess_uses_separate_program_arguments_cwd_and_channels(tmp_path: Path):
    _app()
    runner = QtProcessRunner()
    stdout: list[str] = []
    stderr: list[str] = []
    runner.stdout_text.connect(stdout.append)
    runner.stderr_text.connect(stderr.append)
    runner.start(
        [sys.executable, str(FIXTURE), "--stdout", "out", "--stderr", "err"],
        cwd=tmp_path,
        audit_directory=tmp_path / "audit",
    )
    result = _run(runner)

    assert result.status is ProcessStatus.SUCCEEDED
    assert "".join(stdout) == "out"
    assert "".join(stderr) == "err"
    assert result.stdout_path.read_bytes() == b"out"
    assert result.stderr_path.read_bytes() == b"err"
    assert not runner.is_running


def test_qprocess_start_failure_timeout_and_precancel(tmp_path: Path):
    _app()
    failed_runner = QtProcessRunner()
    failed_runner.start(
        [str(tmp_path / "missing.exe")],
        cwd=tmp_path,
        audit_directory=tmp_path / "failed",
    )
    assert _run(failed_runner).status is ProcessStatus.START_FAILED

    timeout_runner = QtProcessRunner()
    timeout_runner.start(
        [sys.executable, str(FIXTURE), "--delay", "2", "--stdout", "x"],
        cwd=tmp_path,
        audit_directory=tmp_path / "timeout",
        timeout_s=0.05,
        termination_grace_s=0.01,
    )
    assert _run(timeout_runner).status is ProcessStatus.TIMED_OUT

    cancelled_runner = QtProcessRunner()
    cancelled_runner.cancel()
    cancelled_runner.start(
        [sys.executable, str(FIXTURE), "--stdout", "never"],
        cwd=tmp_path,
        audit_directory=tmp_path / "cancelled",
    )
    assert _run(cancelled_runner).status is ProcessStatus.CANCELLED


def test_qprocess_live_cancel_is_idempotent(tmp_path: Path):
    _app()
    runner = QtProcessRunner()
    runner.start(
        [sys.executable, str(FIXTURE), "--delay", "2", "--stdout", "started"],
        cwd=tmp_path,
        audit_directory=tmp_path / "cancel",
        termination_grace_s=0.01,
    )
    QTimer.singleShot(50, runner.cancel)
    QTimer.singleShot(55, runner.cancel)
    result = _run(runner)
    assert result.status is ProcessStatus.CANCELLED
    assert result.duration_seconds < 2


def test_qprocess_cancel_reaps_owned_child_and_preserves_sentinel(tmp_path: Path):
    _app()
    sentinel = psutil.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(30)"]
    )
    runner = QtProcessRunner()
    output: list[str] = []

    def cancel_when_child_is_reported(text: str) -> None:
        output.append(text)
        if "CHILD_PID=" in "".join(output):
            runner.cancel()

    runner.stdout_text.connect(cancel_when_child_is_reported)
    runner.start(
        [sys.executable, str(FIXTURE), "--spawn-child"],
        cwd=tmp_path,
        audit_directory=tmp_path / "tree",
        termination_grace_s=0.01,
    )
    try:
        result = _run(runner)
        child_pid = int(
            "".join(output).split("CHILD_PID=", 1)[1].splitlines()[0]
        )
        deadline = time.monotonic() + 2
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert result.status is ProcessStatus.CANCELLED
        assert not psutil.pid_exists(child_pid)
        assert sentinel.is_running()
    finally:
        sentinel.kill()
        sentinel.wait()
