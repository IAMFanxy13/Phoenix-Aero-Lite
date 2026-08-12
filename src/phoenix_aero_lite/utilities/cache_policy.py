"""Bound generated pipeline caches without following links outside their root."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
from threading import RLock
from typing import Iterable
from uuid import uuid4

import psutil


_CACHE_POLICY_THREAD_LOCK = RLock()
_LEASE_DIRECTORY = ".phoenix-active"


class CacheRunLease:
    """Cross-process lease preventing eviction while a cache run is in use."""

    def __init__(self, cache_root: Path, run_root: Path, marker: Path) -> None:
        self._cache_root = cache_root
        self.run_root = run_root
        self._marker = marker
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        with _cache_policy_lock(self._cache_root):
            self._marker.unlink(missing_ok=True)
            lease_directory = self._marker.parent
            try:
                lease_directory.rmdir()
            except OSError:
                pass
        self._released = True

    def __enter__(self) -> "CacheRunLease":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def acquire_cache_run_lease(run_root: Path) -> CacheRunLease:
    """Create a process-owned lease before a shared cache run is accessed."""

    candidate = Path(run_root).resolve(strict=False)
    runs_root = candidate.parent
    cache_root = runs_root.parent
    if runs_root.name != "runs" or cache_root == runs_root:
        raise ValueError("CACHE_LEASE_RUN_INVALID")
    with _cache_policy_lock(cache_root):
        candidate.mkdir(parents=True, exist_ok=True)
        if candidate.is_symlink() or candidate.resolve(strict=True).parent != runs_root:
            raise ValueError("CACHE_LEASE_RUN_INVALID")
        lease_directory = candidate / _LEASE_DIRECTORY
        lease_directory.mkdir(exist_ok=True)
        marker = lease_directory / f"{os.getpid()}-{uuid4().hex}.json"
        process = psutil.Process(os.getpid())
        marker.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "process_create_time": process.create_time(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    return CacheRunLease(cache_root, candidate, marker)


def enforce_cache_limit(
    root: Path,
    *,
    max_bytes: int,
    protected_runs: Iterable[Path] = (),
) -> dict[str, object]:
    """Remove oldest run directories until regular-file usage is within the cap."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("CACHE_MAX_BYTES_INVALID")
    cache_root = Path(root).resolve(strict=False)
    runs_root = (cache_root / "runs").resolve(strict=False)
    if cache_root.exists() and (cache_root.is_symlink() or not cache_root.is_dir()):
        raise ValueError("CACHE_ROOT_INVALID")
    if runs_root.exists() and (runs_root.is_symlink() or not runs_root.is_dir()):
        raise ValueError("CACHE_RUNS_ROOT_INVALID")
    protected: set[Path] = set()
    for value in protected_runs:
        candidate = Path(value).resolve(strict=False)
        if candidate.parent != runs_root:
            raise ValueError("CACHE_PROTECTED_RUN_INVALID")
        protected.add(candidate)
    with _cache_policy_lock(cache_root):
        if not runs_root.exists():
            return {
                "policy": "oldest-run-first",
                "max_bytes": max_bytes,
                "bytes_before": 0,
                "bytes_after": 0,
                "removed_runs": [],
                "protected_runs": sorted(path.name for path in protected),
                "limit_satisfied": True,
            }

        candidates: list[tuple[float, Path, int]] = []
        for candidate in runs_root.iterdir():
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            resolved = candidate.resolve(strict=True)
            if resolved.parent != runs_root:
                continue
            if _has_live_lease(resolved):
                protected.add(resolved)
            candidates.append(
                (candidate.stat().st_mtime, resolved, _regular_file_bytes(resolved))
            )
        bytes_before = sum(size for _, _, size in candidates)
        bytes_after = bytes_before
        removed: list[str] = []
        for _, candidate, size in sorted(candidates, key=lambda item: item[0]):
            if bytes_after <= max_bytes:
                break
            if candidate in protected:
                continue
            shutil.rmtree(candidate)
            bytes_after -= size
            removed.append(candidate.name)
        return {
            "policy": "oldest-run-first",
            "max_bytes": max_bytes,
            "bytes_before": bytes_before,
            "bytes_after": max(0, bytes_after),
            "removed_runs": removed,
            "protected_runs": sorted(path.name for path in protected),
            "limit_satisfied": bytes_after <= max_bytes,
        }


def _has_live_lease(run_root: Path) -> bool:
    lease_directory = run_root / _LEASE_DIRECTORY
    if not lease_directory.exists():
        return False
    if lease_directory.is_symlink() or not lease_directory.is_dir():
        return False
    live = False
    for marker in lease_directory.glob("*.json"):
        if marker.is_symlink() or not marker.is_file():
            continue
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(payload["pid"])
            expected_create_time = float(payload["process_create_time"])
            process = psutil.Process(pid)
            live = live or abs(process.create_time() - expected_create_time) < 0.01
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, psutil.Error):
            marker.unlink(missing_ok=True)
    if not live:
        try:
            lease_directory.rmdir()
        except OSError:
            pass
    return live


@contextmanager
def _cache_policy_lock(cache_root: Path):
    cache_root.mkdir(parents=True, exist_ok=True)
    lock_path = cache_root / ".cache-policy.lock"
    with _CACHE_POLICY_THREAD_LOCK, lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _regular_file_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            total += path.stat().st_size
    return total
