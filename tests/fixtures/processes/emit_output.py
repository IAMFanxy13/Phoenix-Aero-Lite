"""Deterministic subprocess fixture used by process-runner tests."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", default="")
    parser.add_argument("--stderr", default="")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--spawn-child", action="store_true")
    args = parser.parse_args()

    child: subprocess.Popen[bytes] | None = None
    if args.spawn_child:
        child = subprocess.Popen(
            [sys._base_executable, "-c", "import time; time.sleep(300)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"CHILD_PID={child.pid}", flush=True)

    for _ in range(args.repeat):
        if args.stdout:
            sys.stdout.buffer.write(args.stdout.encode("utf-8"))
            sys.stdout.buffer.flush()
        if args.stderr:
            sys.stderr.buffer.write(args.stderr.encode("utf-8"))
            sys.stderr.buffer.flush()
        if args.delay:
            time.sleep(args.delay)

    if child is not None:
        child.wait()
    return args.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
