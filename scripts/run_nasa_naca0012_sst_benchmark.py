"""Continue the official SU2/NASA NACA0012 SST case with complete evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


NASA_REFERENCE = {
    "source": "NASA NAS Technical Report NAS-2016-01, Table 7.5",
    "url": "https://turbmodels.larc.nasa.gov/Papers/NAS_Technical_Report_NAS-2016-01.pdf",
    "kind": "public_numerical_reference_not_experiment",
    "model": "SST",
    "grid": "897x257",
    "reynolds_number": 6_000_000,
    "angle_of_attack_deg": 0.0,
    "cl": 0.0,
    "cd": 0.00820820,
}


def prepare_continuation_config(source: str, *, iterations: int) -> tuple[str, dict[str, dict[str, str | None]]]:
    if iterations <= 0:
        raise ValueError("BENCHMARK_ITERATIONS_INVALID")
    result = source
    changes: dict[str, dict[str, str | None]] = {}
    for key, value in (("RESTART_SOL", "YES"), ("ITER", str(iterations))):
        pattern = re.compile(rf"(?m)^(\s*{key}\s*=\s*)([^%\r\n]+)")
        match = pattern.search(result)
        if not match:
            raise ValueError(f"BENCHMARK_CONFIG_MISSING_{key}")
        old = match.group(2).strip()
        result = pattern.sub(rf"\g<1>{value}", result, count=1)
        changes[key] = {"from": old, "to": value}
    history = "(ITER, RMS_RES, AERO_COEFF)"
    history_pattern = re.compile(r"(?m)^\s*HISTORY_OUTPUT\s*=\s*([^%\r\n]+)")
    match = history_pattern.search(result)
    if match:
        old = match.group(1).strip()
        result = history_pattern.sub(f"HISTORY_OUTPUT= {history}", result, count=1)
    else:
        old = None
        result += f"\nHISTORY_OUTPUT= {history}\n"
    changes["HISTORY_OUTPUT"] = {"from": old, "to": history}
    return result, changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-evidence", type=Path, required=True)
    parser.add_argument("--su2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=2500)
    args = parser.parse_args()
    source = args.official_evidence.resolve(strict=True)
    executable = args.su2.resolve(strict=True)
    output = args.output.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    names = ("naca0012_SST_SUST.cfg", "mesh_NACA0012_turb_897x257.su2", "restart_flow.dat", "provenance.json")
    inputs = {name: (source / name).resolve(strict=True) for name in names}
    for name, path in inputs.items():
        shutil.copy2(path, output / name)
    staged_restart = stage_restart(inputs["restart_flow.dat"], output)
    config_path = output / "naca0012_SST_SUST.cfg"
    configured, changes = prepare_continuation_config(config_path.read_text(encoding="utf-8-sig"), iterations=args.iterations)
    config_path.write_text(configured, encoding="utf-8", newline="\n")
    command = [str(executable), config_path.name]
    (output / "command.txt").write_text(subprocess.list2cmdline(command) + "\n", encoding="utf-8")
    started = datetime.now(timezone.utc)
    before = time.perf_counter()
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    elapsed = time.perf_counter() - before
    (output / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    (output / "exit_code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
    converged = bool(re.search(r"\|\s*rms\[P\]\s*\|[^\n]*\|\s*Yes\s*\|", completed.stdout, re.IGNORECASE))
    forces = _final_forces(completed.stdout)
    final_cl, final_cd = forces if forces is not None else (None, None)
    summary = {
        "schema_version": 1,
        "started_utc": started.isoformat(),
        "elapsed_seconds": elapsed,
        "command": f"{executable.name} {config_path.name}",
        "exit_code": completed.returncode,
        "execution_passed": completed.returncode == 0,
        "convergence_status": "converged" if converged else "not_converged",
        "final_cl": final_cl,
        "final_cd": final_cd,
        "nasa_reference": NASA_REFERENCE,
        "relative_cd_error": (abs(final_cd - NASA_REFERENCE["cd"]) / NASA_REFERENCE["cd"] if final_cd is not None else None),
        "engineering_validation": False,
        "validation_level": "L2" if completed.returncode == 0 and converged else "L1",
        "configuration_changes": changes,
        "continuation_source": source.name,
        "restart_mapping": {
            "source": "restart_flow.dat",
            "solver_input": staged_restart.name,
            "byte_identical": sha256(staged_restart) == sha256(inputs["restart_flow.dat"]),
        },
        "input_sha256": {name: sha256(path) for name, path in inputs.items()},
        "output_sha256": {
            path.name: sha256(path)
            for path in output.iterdir()
            if path.is_file() and path.name != "validation_summary.json"
        },
    }
    (output / "validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if completed.returncode == 0 and converged else 3


def _final_forces(stdout: str) -> tuple[float, float] | None:
    matches = re.findall(
        r"^\|\s*\d+\s*\|(?:\s*[+-]?[\d.]+(?:[Ee][+-]?\d+)?\s*\|){3}\s*([+-]?[\d.]+(?:[Ee][+-]?\d+)?)\s*\|\s*([+-]?[\d.]+(?:[Ee][+-]?\d+)?)\s*\|",
        stdout,
        flags=re.MULTILINE,
    )
    return tuple(map(float, matches[-1])) if matches else None


def stage_restart(source: Path, output: Path) -> Path:
    """Map official restart output to SU2's configured SOLUTION_FILENAME input."""

    output.mkdir(parents=True, exist_ok=True)
    staged = output / "solution_flow.dat"
    shutil.copy2(source, staged)
    return staged


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
