"""Emit machine-readable runtime diagnostics for release evidence."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

from phoenix_aero_lite.utilities.runtime_discovery import discover_runtime


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    report = discover_runtime(root)
    payload = asdict(report)
    for diagnostic in payload.values():
        if diagnostic["path"] is not None:
            diagnostic["path"] = str(diagnostic["path"])
    payload["ready"] = report.ready
    # ASCII escapes keep evidence readable across Windows PowerShell 5/7 encodings.
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
