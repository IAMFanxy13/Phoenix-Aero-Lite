import multiprocessing
import os
from pathlib import Path

from phoenix_aero_lite.utilities.cache_policy import (
    acquire_cache_run_lease,
    enforce_cache_limit,
)


def _hold_cache_lease(run_root: str, ready, release) -> None:
    lease = acquire_cache_run_lease(Path(run_root))
    ready.set()
    try:
        release.wait(15)
    finally:
        lease.release()


def test_cache_limit_removes_oldest_complete_run_without_crossing_root(tmp_path: Path):
    root = tmp_path / "pipeline-cache"
    oldest = root / "runs" / "oldest"
    newest = root / "runs" / "newest"
    oldest.mkdir(parents=True)
    newest.mkdir(parents=True)
    (oldest / "artifact.bin").write_bytes(b"a" * 8)
    (newest / "artifact.bin").write_bytes(b"b" * 8)
    os.utime(oldest, (1, 1))
    os.utime(newest, (2, 2))

    result = enforce_cache_limit(root, max_bytes=10)

    assert result["policy"] == "oldest-run-first"
    assert result["removed_runs"] == ["oldest"]
    assert result["bytes_after"] == 8
    assert not oldest.exists()
    assert newest.is_dir()


def test_cache_limit_never_removes_a_run_being_materialized(tmp_path: Path):
    root = tmp_path / "pipeline-cache"
    protected = root / "runs" / "protected"
    disposable = root / "runs" / "disposable"
    protected.mkdir(parents=True)
    disposable.mkdir(parents=True)
    (protected / "artifact.bin").write_bytes(b"a" * 8)
    (disposable / "artifact.bin").write_bytes(b"b" * 8)
    os.utime(protected, (1, 1))
    os.utime(disposable, (2, 2))

    result = enforce_cache_limit(
        root,
        max_bytes=5,
        protected_runs=(protected,),
    )

    assert protected.is_dir()
    assert not disposable.exists()
    assert result["protected_runs"] == ["protected"]
    assert result["bytes_after"] == 8
    assert result["limit_satisfied"] is False


def test_live_cross_process_lease_is_automatically_protected(tmp_path: Path):
    root = tmp_path / "pipeline-cache"
    active = root / "runs" / "active"
    disposable = root / "runs" / "disposable"
    active.mkdir(parents=True)
    disposable.mkdir(parents=True)
    (active / "artifact.bin").write_bytes(b"a" * 8)
    (disposable / "artifact.bin").write_bytes(b"b" * 8)
    os.utime(active, (1, 1))
    os.utime(disposable, (2, 2))

    lease = acquire_cache_run_lease(active)
    try:
        result = enforce_cache_limit(root, max_bytes=5)

        assert active.is_dir()
        assert not disposable.exists()
        assert result["protected_runs"] == ["active"]
        assert result["limit_satisfied"] is False
    finally:
        lease.release()

    released = enforce_cache_limit(root, max_bytes=5)
    assert not active.exists()
    assert released["limit_satisfied"] is True


def test_lease_protects_a_run_from_cleanup_in_another_process(tmp_path: Path):
    root = tmp_path / "pipeline-cache"
    active = root / "runs" / "active"
    disposable = root / "runs" / "disposable"
    active.mkdir(parents=True)
    disposable.mkdir(parents=True)
    (active / "artifact.bin").write_bytes(b"a" * 8)
    (disposable / "artifact.bin").write_bytes(b"b" * 8)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_cache_lease,
        args=(str(active), ready, release),
    )
    process.start()
    try:
        assert ready.wait(10)
        result = enforce_cache_limit(root, max_bytes=5)
        assert active.is_dir()
        assert not disposable.exists()
        assert result["protected_runs"] == ["active"]
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0
