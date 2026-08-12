"""Run a pinned official SU2/TestCases NACA0012 SST grid family.

This script downloads only public files from ``su2code/SU2`` and
``su2code/TestCases`` at tag v8.5.0, runs the same audited configuration on
three official meshes, applies Phoenix's independent convergence classifier,
and computes GCI only when every scientific gate passes.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import meshio
import pandas as pd

from phoenix_aero_lite.solver.convergence import (
    ConvergenceExecution,
    classify_convergence,
    convergence_policy,
)
from phoenix_aero_lite.solver.grid_study import (
    AerodynamicGridLevel,
    analyze_aerodynamic_grid_study,
)
from phoenix_aero_lite.solver.su2_history import HistorySample, Su2History


RELEASE_TAG = "v8.5.0"
CONFIG_PATH = "TestCases/rans/naca0012/turb_NACA0012_sst.cfg"
GRID_FILES = {
    "coarse": "n0012_113-33.su2",
    "medium": "n0012_225-65.su2",
    "fine": "n0012_449-129.su2",
}
GRID_DIRECTORY = "rans/naca0012"
_RAW_HOST = "raw.githubusercontent.com"
_GRID_CELL_TYPES = {
    "triangle",
    "quad",
    "triangle6",
    "quad8",
    "quad9",
}


def official_asset_url(repository: str, path: str) -> str:
    """Return a raw URL only for the two pinned official repositories."""

    if (
        repository not in {"SU2", "TestCases"}
        or not path
        or path.startswith(("/", "."))
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError("OFFICIAL_ASSET_INVALID")
    return (
        f"https://{_RAW_HOST}/su2code/{repository}/{RELEASE_TAG}/{path}"
    )


def prepare_grid_config(
    source: str, *, mesh_filename: str, iterations: int
) -> tuple[str, dict[str, dict[str, str | None]]]:
    """Apply only auditable runtime controls to the official SST config."""

    if (
        not re.fullmatch(r"n0012_\d+-\d+\.su2", mesh_filename)
        or not isinstance(iterations, int)
        or isinstance(iterations, bool)
        or iterations < 100
    ):
        raise ValueError("BENCHMARK_CONFIG_INVALID")
    result = source.replace("\r\n", "\n")
    changes: dict[str, dict[str, str | None]] = {}
    for key, value in (
        ("RESTART_SOL", "NO"),
        ("ITER", str(iterations)),
        ("MESH_FILENAME", mesh_filename),
        ("OUTPUT_WRT_FREQ", "100"),
    ):
        result, old = _replace_config_value(result, key, value)
        changes[key] = {"from": old, "to": value}
    history = "(ITER, RMS_RES, AERO_COEFF)"
    result, old = _replace_config_value(
        result, "HISTORY_OUTPUT", history, required=False
    )
    changes["HISTORY_OUTPUT"] = {"from": old, "to": history}
    return result.rstrip() + "\n", changes


def common_setup_fingerprint(config: str) -> str:
    """Hash common physics/numerics while excluding only mesh identity."""

    normalized = re.sub(
        r"(?m)^(\s*MESH_FILENAME\s*=\s*)[^%\r\n]+",
        r"\g<1><OFFICIAL_GRID_FAMILY_MEMBER>",
        config.replace("\r\n", "\n"),
        count=1,
    )
    payload = {
        "release_tag": RELEASE_TAG,
        "config_source": official_asset_url("SU2", CONFIG_PATH),
        "grid_source": official_asset_url("TestCases", GRID_DIRECTORY),
        "normalized_config": normalized,
        "spatial_dimension": 2,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--su2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.threads <= 64:
        raise SystemExit("BENCHMARK_THREADS_INVALID")
    executable = args.su2.resolve(strict=True)
    if executable.name.casefold() != "su2_cfd.exe":
        raise SystemExit("BENCHMARK_SU2_INVALID")
    output = args.output.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    source_root = output / "official_inputs"
    source_root.mkdir(parents=True, exist_ok=True)

    config_url = official_asset_url("SU2", CONFIG_PATH)
    config_source = source_root / "turb_NACA0012_sst.cfg"
    _download_official(config_url, config_source)
    official_config = config_source.read_text(encoding="utf-8-sig")
    levels: list[AerodynamicGridLevel] = []
    level_summaries: dict[str, dict[str, object]] = {}
    fingerprint: str | None = None
    started = datetime.now(timezone.utc)

    for level, mesh_filename in GRID_FILES.items():
        mesh_url = official_asset_url(
            "TestCases", f"{GRID_DIRECTORY}/{mesh_filename}"
        )
        source_mesh = source_root / mesh_filename
        _download_official(mesh_url, source_mesh)
        level_root = output / level
        level_root.mkdir(parents=True, exist_ok=True)
        mesh_path = level_root / mesh_filename
        if not mesh_path.is_file() or _sha256(mesh_path) != _sha256(source_mesh):
            mesh_path.write_bytes(source_mesh.read_bytes())
        configured, changes = prepare_grid_config(
            official_config,
            mesh_filename=mesh_filename,
            iterations=args.iterations,
        )
        current_fingerprint = common_setup_fingerprint(configured)
        fingerprint = fingerprint or current_fingerprint
        config_path = level_root / "turb_NACA0012_sst.cfg"
        config_path.write_text(configured, encoding="utf-8", newline="\n")
        command = [
            str(executable),
            "-t",
            str(args.threads),
            config_path.name,
        ]
        (level_root / "command.txt").write_text(
            subprocess.list2cmdline(command) + "\n", encoding="utf-8"
        )
        before = time.perf_counter()
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=level_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        elapsed = time.perf_counter() - before
        (level_root / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (level_root / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        (level_root / "exit_code.txt").write_text(
            f"{completed.returncode}\n", encoding="utf-8"
        )
        node_count, cell_count = _mesh_counts(mesh_path)
        summary = _summarize_level(
            level=level,
            level_root=level_root,
            node_count=node_count,
            cell_count=cell_count,
            exit_code=completed.returncode,
            elapsed_seconds=elapsed,
            iterations=args.iterations,
            fingerprint=current_fingerprint,
            config_changes=changes,
            source_urls={"config": config_url, "mesh": mesh_url},
        )
        level_summaries[level] = summary
        _write_json(level_root / "level_summary.json", summary)
        if summary["final_cl"] is not None and summary["final_cd"] is not None:
            levels.append(
                AerodynamicGridLevel(
                    level=level,
                    node_count=node_count,
                    cell_count=cell_count,
                    cl=float(summary["final_cl"]),
                    cd=float(summary["final_cd"]),
                    convergence_status=str(summary["convergence_status"]),
                    common_setup_fingerprint=current_fingerprint,
                    elapsed_seconds=elapsed,
                    spatial_dimension=2,
                )
            )

    study: dict[str, object]
    if len(levels) == 3 and tuple(item.level for item in levels) == tuple(GRID_FILES):
        quantities = analyze_aerodynamic_grid_study(
            coarse=levels[0], medium=levels[1], fine=levels[2]
        )
        fully_computable = all(item.gci_computable for item in quantities.values())
        study = {
            "status": "computed" if fully_computable else "blocked",
            "quantities": {
                name: result.to_dict() for name, result in quantities.items()
            },
        }
    else:
        fully_computable = False
        study = {
            "status": "blocked",
            "blocking_reasons": ["GRID_LEVEL_RESULT_INCOMPLETE"],
        }
    payload = {
        "schema_version": 1,
        "started_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "official_sources_only": True,
        "release_tag": RELEASE_TAG,
        "solver": str(executable),
        "threads": args.threads,
        "iterations_per_level": args.iterations,
        "common_setup_fingerprint": fingerprint,
        "levels": level_summaries,
        "grid_study": study,
        "validation_level": "L3" if fully_computable else "L1",
        "engineering_validation": False,
        "limitations": [
            "This public numerical benchmark is not experimental validation.",
            "A process exit code of zero is not treated as convergence.",
            "L3 is assigned only when every level and every reported GCI gate passes.",
        ],
    }
    payload["artifact_sha256"] = _artifact_hashes(output)
    _write_json(output / "validation_summary.json", payload)
    return 0 if fully_computable else 3


def _replace_config_value(
    source: str, key: str, value: str, *, required: bool = True
) -> tuple[str, str | None]:
    pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s*=\s*)([^%\r\n]+)")
    match = pattern.search(source)
    if match:
        old = match.group(2).strip()
        return pattern.sub(rf"\g<1>{value}", source, count=1), old
    if required:
        raise ValueError(f"BENCHMARK_CONFIG_MISSING_{key}")
    return source.rstrip() + f"\n{key}= {value}\n", None


def _download_official(url: str, destination: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _RAW_HOST:
        raise ValueError("OFFICIAL_ASSET_URL_INVALID")
    if destination.is_file() and destination.stat().st_size > 0:
        return
    request = Request(url, headers={"User-Agent": "Phoenix-Aero-Lite-validation"})
    with urlopen(request, timeout=120) as response:  # noqa: S310
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != _RAW_HOST:
            raise ValueError("OFFICIAL_ASSET_REDIRECT_INVALID")
        content = response.read()
    if not content:
        raise RuntimeError("OFFICIAL_ASSET_EMPTY")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(destination)


def _mesh_counts(path: Path) -> tuple[int, int]:
    mesh = meshio.read(path)
    cell_count = sum(
        len(block.data) for block in mesh.cells if block.type in _GRID_CELL_TYPES
    )
    if len(mesh.points) <= 0 or cell_count <= 0:
        raise RuntimeError("BENCHMARK_MESH_EMPTY")
    return len(mesh.points), cell_count


def _summarize_level(
    *,
    level: str,
    level_root: Path,
    node_count: int,
    cell_count: int,
    exit_code: int,
    elapsed_seconds: float,
    iterations: int,
    fingerprint: str,
    config_changes: dict[str, dict[str, str | None]],
    source_urls: dict[str, str],
) -> dict[str, object]:
    history_path = level_root / "history.csv"
    final_cl: float | None = None
    final_cd: float | None = None
    status = "invalid"
    reason = "HISTORY_MISSING"
    diagnostics: dict[str, object] = {}
    if history_path.is_file() and history_path.stat().st_size > 0:
        history = _parse_compressible_history(history_path)
        execution = ConvergenceExecution(
            process_status="succeeded" if exit_code == 0 else "nonzero_exit",
            exit_code=exit_code,
            history_complete=_csv_history_complete(history_path),
        )
        result = classify_convergence(
            history,
            convergence_policy("benchmark", iterations),
            execution=execution,
        )
        status = result.status.value
        reason = result.reason_code
        final_cl = result.final_cl
        final_cd = result.final_cd
        diagnostics = dict(result.diagnostics)
    return {
        "level": level,
        "node_count": node_count,
        "cell_count": cell_count,
        "final_cl": final_cl,
        "final_cd": final_cd,
        "convergence_status": status,
        "convergence_reason": reason,
        "convergence_diagnostics": diagnostics,
        "exit_code": exit_code,
        "execution_passed": exit_code == 0,
        "elapsed_seconds": elapsed_seconds,
        "common_setup_fingerprint": fingerprint,
        "config_changes": config_changes,
        "source_urls": source_urls,
        "sha256": {
            path.name: _sha256(path)
            for path in level_root.iterdir()
            if path.is_file() and path.name != "level_summary.json"
        },
    }


def _parse_compressible_history(path: Path) -> Su2History:
    frame = pd.read_csv(path, skipinitialspace=True)
    frame.columns = [str(column).strip() for column in frame.columns]

    def column(*candidates: str) -> str:
        for candidate in candidates:
            if candidate in frame.columns:
                return candidate
        raise ValueError("BENCHMARK_HISTORY_COLUMNS_MISSING")

    iteration = column("Inner_Iter", "Iteration")
    residual = column("rms[Rho]", "rms[Density]", "rms[P]")
    tke = column("rms[k]", "rms[TKE]")
    omega = column("rms[w]", "rms[omega]", "rms[Dissipation]")
    cl_name = column("CL")
    cd_name = column("CD")
    samples: list[HistorySample] = []
    for row in frame.to_dict(orient="records"):
        values = [row[name] for name in (iteration, residual, tke, omega, cl_name, cd_name)]
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("BENCHMARK_HISTORY_NONFINITE")
        samples.append(
            HistorySample(
                iteration=int(float(row[iteration])),
                rms_pressure=float(row[residual]),
                rms_tke=float(row[tke]),
                rms_omega=float(row[omega]),
                cl=float(row[cl_name]),
                cd=float(row[cd_name]),
                force_x=None,
                force_y=None,
                force_z=None,
            )
        )
    return Su2History(path.resolve(strict=True), tuple(samples))


def _csv_history_complete(path: Path) -> bool:
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line]
    if len(lines) < 2:
        return False
    return len(next(csv.reader([lines[0]]))) == len(next(csv.reader([lines[-1]])))


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "validation_summary.json"
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
