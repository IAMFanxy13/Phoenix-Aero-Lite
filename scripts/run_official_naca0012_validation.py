"""Run the unmodified official SU2 v8.5.0 QuickStart and save evidence."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


OFFICIAL_REGRESSION = {
    "cl": 0.338691,
    "cd": 0.023131,
    "source": "https://su2code.github.io/documents/dev_meeting_2018/00_su2_hackathon_economon.pdf",
    "scope": "Historical official SU2 NACA0012 regression value; comparison is informative because solver/version changes can shift the exact result.",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("su2", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    executable = args.su2.resolve(strict=True)
    output = args.output.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    names = ("inv_NACA0012.cfg", "mesh_NACA0012_inv.su2")
    for name in names:
        shutil.copy2(source / name, output / name)

    command = [str(executable), "inv_NACA0012.cfg"]
    started = datetime.now(timezone.utc)
    before = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=output,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15 * 60,
        check=False,
    )
    elapsed = time.perf_counter() - before
    (output / "command.txt").write_text(
        subprocess.list2cmdline(command) + "\n", encoding="utf-8"
    )
    (output / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    (output / "exit_code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
    coefficients = parse_coefficients(completed.stdout)
    with (output / "coefficients.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("iteration", "cl", "cd"))
        writer.writeheader()
        writer.writerows(coefficients)
    final = coefficients[-1] if coefficients else {}
    expected_cl = OFFICIAL_REGRESSION["cl"]
    expected_cd = OFFICIAL_REGRESSION["cd"]
    summary = {
        "case": "Official SU2 v8.5.0 QuickStart inv_NACA0012",
        "official_source": "https://github.com/su2code/SU2/tree/v8.5.0/QuickStart",
        "official_source_commit": "12eb826f049ef7f67df974dfcb44cf36ee07c0f8",
        "su2_executable": str(executable),
        "started_utc": started.isoformat(),
        "elapsed_seconds": elapsed,
        "exit_code": completed.returncode,
        "history_exists": (output / "history.csv").is_file(),
        "flow_exists": (output / "flow.vtu").is_file(),
        "converged_banner": "All convergence criteria satisfied" in completed.stdout,
        "final_iteration": final.get("iteration"),
        "final_cl": final.get("cl"),
        "final_cd": final.get("cd"),
        "historical_official_regression": OFFICIAL_REGRESSION,
        "cl_relative_error_percent": relative_error(final.get("cl"), expected_cl),
        "cd_relative_error_percent": relative_error(final.get("cd"), expected_cd),
        "comparison_note_zh": "公开对照来自 SU2 官方旧版回归材料，不是风洞实验；用于验证量级和回归，不把版本差异伪装成实验误差。",
        "files_sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in names
        },
    }
    (output / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if all(
        (
            completed.returncode == 0,
            summary["history_exists"],
            summary["flow_exists"],
            summary["converged_banner"],
            bool(coefficients),
        )
    ) else 1


def parse_coefficients(stdout: str) -> list[dict[str, float | int]]:
    pattern = re.compile(
        r"^\|\s*(\d+)\|(?:\s*[-+0-9.eE]+\|){6}\s*([-+0-9.eE]+)\|\s*([-+0-9.eE]+)\|$"
    )
    rows = []
    for line in stdout.splitlines():
        match = pattern.match(line)
        if match:
            rows.append(
                {
                    "iteration": int(match.group(1)),
                    "cl": float(match.group(2)),
                    "cd": float(match.group(3)),
                }
            )
    return rows


def relative_error(actual: float | None, expected: float) -> float | None:
    if actual is None:
        return None
    return abs(actual - expected) / abs(expected) * 100.0


if __name__ == "__main__":
    raise SystemExit(main())
