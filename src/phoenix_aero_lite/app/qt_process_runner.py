"""Qt event-loop adapter for audited shell-free process execution."""

from __future__ import annotations

import codecs
from datetime import datetime, timezone
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import psutil
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from phoenix_aero_lite.utilities.process_runner import (
    ProcessResult,
    ProcessStatus,
    _prepare_logs,
    _validate_argv,
    _validate_cwd,
    _validate_environment,
    _validate_timeout,
)


class QtProcessRunner(QObject):
    """Own one QProcess and emit separated live output plus immutable evidence."""

    stdout_text = Signal(str)
    stderr_text = Signal(str)
    completed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_kill)
        self._stdout_decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
        self._stderr_decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
        self._active = False
        self._cancel_requested = False
        self._terminal_override: ProcessStatus | None = None
        self._owned_descendants: list[psutil.Process] = []

    @property
    def is_running(self) -> bool:
        """Whether this adapter currently owns an active attempt."""

        return self._active

    def start(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        audit_directory: Path,
        environment_delta: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        termination_grace_s: float = 1.0,
    ) -> None:
        """Validate and asynchronously start a QProcess without a shell."""

        if self._active:
            raise RuntimeError("QT_PROCESS_ALREADY_RUNNING")
        self._argv = _validate_argv(argv)
        self._cwd = _validate_cwd(cwd)
        self._environment_delta = _validate_environment(
            environment_delta or {}
        )
        self._timeout_s = _validate_timeout(timeout_s, optional=True)
        self._grace_s = _validate_timeout(
            termination_grace_s, optional=False
        )
        self._stdout_path, self._stderr_path = _prepare_logs(audit_directory)
        self._stdout_log = self._stdout_path.open("xb")
        self._stderr_log = self._stderr_path.open("xb")
        self._started_at = datetime.now(timezone.utc)
        self._active = True
        self._terminal_override = None
        self._owned_descendants = []
        self._stdout_decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
        self._stderr_decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )

        if self._cancel_requested:
            QTimer.singleShot(
                0, lambda: self._finish(None, ProcessStatus.CANCELLED)
            )
            return

        environment = QProcessEnvironment.systemEnvironment()
        for key, value in self._environment_delta.items():
            environment.insert(key, value)
        self._process.setProcessEnvironment(environment)
        self._process.setProgram(self._argv[0])
        self._process.setArguments(list(self._argv[1:]))
        self._process.setWorkingDirectory(str(self._cwd))
        self._process.start()
        if self._timeout_s is not None:
            self._timeout_timer.start(max(1, round(self._timeout_s * 1000)))

    def cancel(self) -> None:
        """Request cancellation; repeated calls are harmless."""

        self._cancel_requested = True
        if self._active and self._process.state() != QProcess.NotRunning:
            self._begin_termination(ProcessStatus.CANCELLED)

    def _read_stdout(self) -> None:
        self._consume(
            bytes(self._process.readAllStandardOutput()),
            self._stdout_log,
            self._stdout_decoder,
            self.stdout_text,
        )

    def _read_stderr(self) -> None:
        self._consume(
            bytes(self._process.readAllStandardError()),
            self._stderr_log,
            self._stderr_decoder,
            self.stderr_text,
        )

    @staticmethod
    def _consume(data: bytes, log, decoder, signal_emitter) -> None:
        if not data:
            return
        log.write(data)
        log.flush()
        text = decoder.decode(data)
        if text:
            signal_emitter.emit(text)

    def _on_timeout(self) -> None:
        if self._active and not self._cancel_requested:
            self._begin_termination(ProcessStatus.TIMED_OUT)

    def _begin_termination(self, status: ProcessStatus) -> None:
        if self._terminal_override is None:
            self._terminal_override = status
        try:
            root = psutil.Process(int(self._process.processId()))
            self._owned_descendants = root.children(recursive=True)
        except psutil.Error:
            self._owned_descendants = []
        self._process.terminate()
        self._kill_timer.start(max(1, round(self._grace_s * 1000)))

    def _force_kill(self) -> None:
        self._kill_owned_descendants()
        if self._process.state() != QProcess.NotRunning:
            self._process.kill()

    def _kill_owned_descendants(self) -> None:
        for process in self._owned_descendants:
            try:
                process.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(self._owned_descendants, timeout=0.2)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart and self._active:
            QTimer.singleShot(
                0, lambda: self._finish(None, ProcessStatus.START_FAILED)
            )

    def _on_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        if not self._active:
            return
        self._read_stdout()
        self._read_stderr()
        if self._terminal_override is not None:
            # QProcess.terminate() can end the direct process before its
            # descendants.  The owned snapshot must still be reaped.
            self._kill_owned_descendants()
            status = self._terminal_override
        elif exit_code == 0:
            status = ProcessStatus.SUCCEEDED
        else:
            status = ProcessStatus.NONZERO_EXIT
        self._finish(exit_code, status)

    def _finish(
        self,
        exit_code: int | None,
        status: ProcessStatus,
    ) -> None:
        if not self._active:
            return
        self._timeout_timer.stop()
        self._kill_timer.stop()
        for decoder, emitter in (
            (self._stdout_decoder, self.stdout_text),
            (self._stderr_decoder, self.stderr_text),
        ):
            tail = decoder.decode(b"", final=True)
            if tail:
                emitter.emit(tail)
        for log in (self._stdout_log, self._stderr_log):
            log.flush()
            os.fsync(log.fileno())
            log.close()
        result = ProcessResult(
            argv=self._argv,
            exit_code=exit_code,
            status=status,
            started_at=self._started_at,
            ended_at=datetime.now(timezone.utc),
            cwd=self._cwd,
            environment_delta=MappingProxyType(
                dict(self._environment_delta)
            ),
            stdout_path=self._stdout_path,
            stderr_path=self._stderr_path,
        )
        self._active = False
        self._cancel_requested = False
        self.completed.emit(result)
