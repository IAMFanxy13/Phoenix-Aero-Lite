"""Create a history-free, scanned public source export from tracked files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from uuid import uuid4


_EXCLUDED_PREFIXES = (
    "artifacts/",
    "build/",
    "cases/",
    "config/local_tools.json",
    "dist/",
    "docs/reviews/",
    "docs/superpowers/",
    "tests/local/",
    "web-data/",
)
_EXCLUDED_FILES = {
    "docs/research/environment_inventory.md",
    "docs/research/su2_windows_installation.md",
    "tests/unit/solver/test_air_step_regression.py",
}
_PUBLIC_ARTIFACTS = {
    "artifacts/e2e/browser_errors.json",
    "artifacts/e2e/public_workbench_surface_selected.png",
    "artifacts/e2e/public_workbench_y_plus.png",
}


def is_public_release_excluded(relative_path: str) -> bool:
    normalized = PurePosixPath(str(relative_path).replace("\\", "/")).as_posix()
    folded = normalized.casefold()
    if normalized in _PUBLIC_ARTIFACTS:
        return False
    if normalized in _EXCLUDED_FILES:
        return True
    if folded.startswith("tests/fixtures/su2/air_step_real_history"):
        return True
    return any(folded.startswith(prefix.casefold()) for prefix in _EXCLUDED_PREFIXES)


def sanitize_public_text(text: str) -> str:
    """Redact private model identifiers while preserving file-type semantics."""

    private_step = "Air" + ".STEP"
    private_cad = "Air" + ".SLDPRT"
    private_alias = "feiji" + ".STEP"
    sanitized = text.replace(private_step, "example_model.STEP")
    sanitized = sanitized.replace(private_cad, "example_model.SLDPRT")
    sanitized = sanitized.replace(private_alias, "example_model.STEP")
    return sanitized


def find_sensitive_text(
    text: str,
    *,
    private_hashes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    checks = (
        ("LOCAL_WINDOWS_PATH", re.compile(r"(?i)[A-Z]:\\Users\\")),
        ("PRIVATE_MODEL_NAME", re.compile(r"\b(?:Air\.(?:STEP|SLDPRT)|feiji\.STEP)\b")),
        ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
        ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
        ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
        (
            "EMAIL_ADDRESS",
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        ),
    )
    findings = [name for name, pattern in checks if pattern.search(text)]
    normalized_private_hashes = {
        value.strip().upper() for value in private_hashes if value.strip()
    }
    if any(value in text.upper() for value in normalized_private_hashes):
        findings.append("PRIVATE_MODEL_HASH")
    return tuple(findings)


def export_public_release(
    source_root: Path,
    destination: Path,
    *,
    private_hashes: tuple[str, ...] = (),
) -> dict[str, object]:
    requested_source = Path(source_root)
    if requested_source.is_symlink():
        raise ValueError("PUBLIC_EXPORT_UNSAFE_SOURCE_PATH")
    source = requested_source.resolve(strict=True)
    target = Path(destination).resolve(strict=False)
    if target.exists() and any(target.iterdir()):
        raise ValueError("PUBLIC_EXPORT_DESTINATION_NOT_EMPTY")
    denied_hashes = _normalized_private_hashes(private_hashes)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.tmp-{uuid4().hex}"
    staging.mkdir()
    try:
        tracked = _tracked_entries(source)
        copied: list[dict[str, object]] = []
        excluded: list[str] = []
        findings: list[dict[str, str]] = []
        for mode, relative in sorted(tracked, key=lambda item: item[1]):
            normalized = PurePosixPath(relative).as_posix()
            if is_public_release_excluded(normalized):
                excluded.append(normalized)
                continue
            if mode == "120000":
                raise ValueError("PUBLIC_EXPORT_UNSAFE_SOURCE_PATH")
            if find_sensitive_text(normalized, private_hashes=tuple(denied_hashes)):
                findings.append({"path": normalized, "finding": "SENSITIVE_FILENAME"})
                continue
            candidate = source / Path(normalized)
            if candidate.is_symlink():
                raise ValueError("PUBLIC_EXPORT_UNSAFE_SOURCE_PATH")
            source_path = candidate.resolve(strict=True)
            if not source_path.is_relative_to(source) or not source_path.is_file():
                raise ValueError("PUBLIC_EXPORT_UNSAFE_SOURCE_PATH")
            source_digest = _sha256(source_path)
            if source_digest in denied_hashes:
                raise ValueError("PUBLIC_EXPORT_PRIVATE_HASH_DENIED")
            output_path = (staging / Path(normalized)).resolve(strict=False)
            if not output_path.is_relative_to(staging):
                raise ValueError("PUBLIC_EXPORT_UNSAFE_SOURCE_PATH")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = source_path.read_bytes()
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None and "\x00" not in text:
                text = sanitize_public_text(text)
                for finding in find_sensitive_text(
                    text, private_hashes=tuple(denied_hashes)
                ):
                    findings.append({"path": normalized, "finding": finding})
                if output_path.suffix.casefold() in {".cmd", ".bat"}:
                    text = text.replace("\r\n", "\n").replace("\r", "\n")
                    output_path.write_text(text, encoding="utf-8", newline="\r\n")
                else:
                    output_path.write_text(text, encoding="utf-8", newline="")
            else:
                shutil.copyfile(source_path, output_path)
            output_digest = _sha256(output_path)
            if output_digest in denied_hashes:
                raise ValueError("PUBLIC_EXPORT_PRIVATE_HASH_DENIED")
            copied.append(
                {
                    "path": normalized,
                    "size": output_path.stat().st_size,
                    "sha256": output_digest,
                }
            )
        commit = _git(source, "rev-parse", "HEAD").strip()
        report = {
            "schema_version": 2,
            "source_commit": commit,
            "history_included": False,
            "private_hash_deny_count": len(denied_hashes),
            "copied_file_count": len(copied),
            "excluded_file_count": len(excluded),
            "sensitive_findings": findings,
            "excluded_files": excluded,
        }
        (staging / "PUBLIC_EXPORT_SANITIZATION.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="",
        )
        (staging / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "source_commit": commit,
                    "files": copied,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="",
        )
        if findings:
            raise ValueError("PUBLIC_EXPORT_SENSITIVE_CONTENT_FOUND")
        if target.exists():
            target.rmdir()
        os.replace(staging, target)
        return report
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _normalized_private_hashes(values: tuple[str, ...]) -> frozenset[str]:
    normalized: set[str] = set()
    for raw_value in values:
        if not isinstance(raw_value, str):
            raise ValueError("PUBLIC_EXPORT_PRIVATE_HASH_INVALID")
        value = raw_value.strip().upper()
        if len(value) != 64 or any(
            character not in "0123456789ABCDEF" for character in value
        ):
            raise ValueError("PUBLIC_EXPORT_PRIVATE_HASH_INVALID")
        normalized.add(value)
    return frozenset(normalized)


def _tracked_entries(source: Path) -> tuple[tuple[str, str], ...]:
    raw = _git(source, "ls-files", "-s", "-z")
    entries: list[tuple[str, str]] = []
    for record in raw.split("\0"):
        if not record:
            continue
        metadata, separator, relative = record.partition("\t")
        if not separator:
            raise RuntimeError("PUBLIC_EXPORT_GIT_INDEX_INVALID")
        mode = metadata.split(" ", 1)[0]
        entries.append((mode, relative))
    return tuple(entries)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError("PUBLIC_EXPORT_GIT_FAILED")
    return completed.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument(
        "--deny-sha256",
        action="append",
        default=[],
        metavar="SHA256",
        help="Reject a private input SHA-256 without storing it in the repository.",
    )
    args = parser.parse_args(argv)
    try:
        report = export_public_release(
            args.source,
            args.destination,
            private_hashes=tuple(args.deny_sha256),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
