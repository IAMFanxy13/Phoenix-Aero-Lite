"""Audited, shell-free external process execution."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

import psutil


class ProcessRunnerError(ValueError):
    """Stable process-runner boundary error."""


class ProcessStatus(str, Enum):
    """Terminal process states used by CLI, GUI, manifests, and reports."""

    SUCCEEDED = "succeeded"
    NONZERO_EXIT = "nonzero_exit"
    START_FAILED = "start_failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Immutable audit evidence for one process attempt."""

    argv: tuple[str, ...]
    exit_code: int | None
    status: ProcessStatus
    started_at: datetime
    ended_at: datetime
    cwd: Path
    environment_delta: Mapping[str, str]
    stdout_path: Path
    stderr_path: Path

    @property
    def duration_seconds(self) -> float:
        """Return the non-negative wall-clock duration."""

        return max(0.0, (self.ended_at - self.started_at).total_seconds())


class CancellationToken:
    """Thread-safe, idempotent cancellation request."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation."""

        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""

        return self._event.is_set()


TextCallback = Callable[[str], None]


def run_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    audit_directory: Path,
    environment_delta: Mapping[str, str] | None = None,
    timeout_s: float | None = None,
    cancellation: CancellationToken | None = None,
    on_stdout: TextCallback | None = None,
    on_stderr: TextCallback | None = None,
    termination_grace_s: float = 1.0,
) -> ProcessResult:
    """Run an absolute executable without a shell and preserve raw audit logs."""

    normalized_argv = _validate_argv(argv)
    working_directory = _validate_cwd(cwd)
    delta = _validate_environment(environment_delta or {})
    timeout = _validate_timeout(timeout_s, optional=True)
    grace = _validate_timeout(termination_grace_s, optional=False)
    stdout_path, stderr_path = _prepare_logs(audit_directory)
    token = cancellation or CancellationToken()
    started_at = datetime.now(timezone.utc)

    with stdout_path.open("xb") as stdout_log, stderr_path.open("xb") as stderr_log:
        if token.is_cancelled:
            return _result(
                normalized_argv,
                None,
                ProcessStatus.CANCELLED,
                started_at,
                working_directory,
                delta,
                stdout_path,
                stderr_path,
            )

        environment = os.environ.copy()
        environment.update(delta)
        popen_options: dict[str, object] = {}
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
        try:
            process = subprocess.Popen(
                normalized_argv,
                cwd=working_directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                **popen_options,
            )
        except OSError:
            return _result(
                normalized_argv,
                None,
                ProcessStatus.START_FAILED,
                started_at,
                working_directory,
                delta,
                stdout_path,
                stderr_path,
            )

        assert process.stdout is not None
        assert process.stderr is not None
        readers = (
            threading.Thread(
                target=_copy_stream,
                args=(process.stdout, stdout_log, on_stdout),
                daemon=True,
            ),
            threading.Thread(
                target=_copy_stream,
                args=(process.stderr, stderr_log, on_stderr),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()

        monotonic_start = time.monotonic()
        terminal_override: ProcessStatus | None = None
        while process.poll() is None:
            if token.is_cancelled:
                terminal_override = ProcessStatus.CANCELLED
                _terminate_owned_tree(process, grace)
                break
            if timeout is not None and time.monotonic() - monotonic_start >= timeout:
                terminal_override = ProcessStatus.TIMED_OUT
                _terminate_owned_tree(process, grace)
                break
            time.sleep(0.01)

        try:
            exit_code = process.wait(timeout=max(grace, 0.1))
        except subprocess.TimeoutExpired:
            _terminate_owned_tree(process, 0.0)
            exit_code = process.wait()
        for reader in readers:
            reader.join(timeout=5.0)
        stdout_log.flush()
        stderr_log.flush()
        os.fsync(stdout_log.fileno())
        os.fsync(stderr_log.fileno())

    if terminal_override is not None:
        status = terminal_override
    elif exit_code == 0:
        status = ProcessStatus.SUCCEEDED
    else:
        status = ProcessStatus.NONZERO_EXIT
    return _result(
        normalized_argv,
        exit_code,
        status,
        started_at,
        working_directory,
        delta,
        stdout_path,
        stderr_path,
    )


def _validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise ProcessRunnerError("PROCESS_ARGV_INVALID")
    try:
        normalized = tuple(argv)
    except TypeError:
        raise ProcessRunnerError("PROCESS_ARGV_INVALID") from None
    if (
        not normalized
        or any(
            not isinstance(item, str) or not item or "\0" in item
            for item in normalized
        )
        or not Path(normalized[0]).is_absolute()
    ):
        raise ProcessRunnerError("PROCESS_ARGV_INVALID")
    return normalized


def _validate_cwd(cwd: Path) -> Path:
    if not isinstance(cwd, Path) or not cwd.is_dir():
        raise ProcessRunnerError("PROCESS_CWD_INVALID")
    resolved = cwd.resolve(strict=True)
    if _is_redirecting(cwd):
        raise ProcessRunnerError("PROCESS_CWD_UNSAFE")
    return resolved


def _validate_environment(values: Mapping[str, str]) -> dict[str, str]:
    try:
        items = tuple(values.items())
    except (AttributeError, TypeError):
        raise ProcessRunnerError("PROCESS_ENV_INVALID") from None
    if any(
        not isinstance(key, str)
        or not key
        or "=" in key
        or "\0" in key
        or not isinstance(value, str)
        or "\0" in value
        for key, value in items
    ):
        raise ProcessRunnerError("PROCESS_ENV_INVALID")
    return dict(items)


def _validate_timeout(value: float | None, *, optional: bool) -> float | None:
    if value is None and optional:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ProcessRunnerError("PROCESS_TIMEOUT_INVALID")
    return float(value)


def _prepare_logs(audit_directory: Path) -> tuple[Path, Path]:
    if (
        not isinstance(audit_directory, Path)
        or not audit_directory.name
        or ".." in audit_directory.parts
    ):
        raise ProcessRunnerError("PROCESS_LOG_PATH_UNSAFE")
    requested = (
        audit_directory
        if audit_directory.is_absolute()
        else Path.cwd() / audit_directory
    )
    _reject_redirecting_ancestors(requested)
    requested.parent.mkdir(parents=True, exist_ok=True)
    audit = requested.parent.resolve(strict=True) / requested.name
    if audit.exists():
        if not audit.is_dir() or _is_redirecting(audit):
            raise ProcessRunnerError("PROCESS_LOG_PATH_UNSAFE")
    else:
        audit.mkdir()
    stdout_path = audit / "stdout.bin"
    stderr_path = audit / "stderr.bin"
    if stdout_path.exists() or stderr_path.exists():
        raise ProcessRunnerError("PROCESS_LOG_COLLISION")
    return stdout_path.resolve(strict=False), stderr_path.resolve(strict=False)


def _reject_redirecting_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and _is_redirecting(current):
            raise ProcessRunnerError("PROCESS_LOG_PATH_UNSAFE")
        if current.parent == current:
            return
        current = current.parent


def _is_redirecting(path: Path) -> bool:
    return path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _copy_stream(stream, destination, callback: TextCallback | None) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    read_available = getattr(stream, "read1", stream.read)
    while True:
        chunk = read_available(65536)
        if not chunk:
            break
        destination.write(chunk)
        destination.flush()
        text = decoder.decode(chunk)
        if text and callback is not None:
            try:
                callback(text)
            except Exception:
                pass
    tail = decoder.decode(b"", final=True)
    if tail and callback is not None:
        try:
            callback(tail)
        except Exception:
            pass


def _terminate_owned_tree(process: subprocess.Popen[bytes], grace: float) -> None:
    try:
        root = psutil.Process(process.pid)
        descendants = root.children(recursive=True)
    except psutil.Error:
        descendants = []
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    owned: list[psutil.Process] = descendants
    try:
        owned.append(psutil.Process(process.pid))
    except psutil.Error:
        pass
    for owned_process in owned:
        try:
            owned_process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(owned, timeout=grace)
    for owned_process in alive:
        try:
            owned_process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=max(grace, 0.1))


def _result(
    argv: tuple[str, ...],
    exit_code: int | None,
    status: ProcessStatus,
    started_at: datetime,
    cwd: Path,
    environment_delta: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> ProcessResult:
    return ProcessResult(
        argv=argv,
        exit_code=exit_code,
        status=status,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        cwd=cwd,
        environment_delta=MappingProxyType(dict(environment_delta)),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
