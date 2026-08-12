"""Run one upstream validation command and persist an audit trail.

This is research infrastructure, not Phoenix Aero Lite product code. It keeps
the invoked argument vector, working directory, timestamps, stdout, stderr and
return code together so a validation result cannot be separated from evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EVIDENCE_FILES = ("command.txt", "metadata.json", "stdout.txt", "stderr.txt")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="Stable validation directory name")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if SAFE_ID.fullmatch(args.id) is None:
        print(
            "validation id must be one safe directory name: letters, digits, dot, underscore or hyphen",
            file=sys.stderr,
        )
        return 2
    evidence_dir = (root / args.id).resolve()
    if evidence_dir.parent != root:
        print("validation evidence directory escaped its root", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    try:
        evidence_dir.mkdir()
    except FileExistsError:
        print(f"refusing to overwrite existing evidence: {evidence_dir}", file=sys.stderr)
        return 2
    cwd = args.cwd.resolve()
    started_at = utc_now()
    exception: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None

    try:
        completed = subprocess.run(
            args.command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        launch_state = "completed"
    except FileNotFoundError as error:
        exit_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
        exception = repr(error)
        exception_type = type(error).__name__
        exception_message = str(error)
        launch_state = "not_found"
    except OSError as error:
        exit_code = 126
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
        exception = repr(error)
        exception_type = type(error).__name__
        exception_message = str(error)
        launch_state = "launch_failed"

    ended_at = utc_now()
    command_line = subprocess.list2cmdline(args.command)
    metadata = {
        "schema_version": 2,
        "id": args.id,
        "command": args.command,
        "command_line": command_line,
        "working_directory": str(cwd),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "exit_code": exit_code,
        "launch_state": launch_state,
        "exception": exception,
        "exception_type": exception_type,
        "exception_message": exception_message,
        "stdout_file": "stdout.txt",
        "stderr_file": "stderr.txt",
    }

    evidence_contents = {
        "command.txt": command_line + "\n",
        "stdout.txt": stdout,
        "stderr.txt": stderr,
        "metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    }
    for name in EVIDENCE_FILES:
        with (evidence_dir / name).open("x", encoding="utf-8") as evidence_file:
            evidence_file.write(evidence_contents[name])
    print(json.dumps(metadata, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
