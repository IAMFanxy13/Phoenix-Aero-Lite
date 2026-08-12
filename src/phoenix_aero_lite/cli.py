"""Non-interactive entry points for Phoenix Aero Lite."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import sys
from typing import Callable

from phoenix_aero_lite.app.pipeline import PhoenixCasePipeline
from phoenix_aero_lite.solver.credibility import assess_credibility
from phoenix_aero_lite.solver.grid_study import (
    AerodynamicGridLevel,
    analyze_aerodynamic_grid_study,
)
from phoenix_aero_lite.models.parameters import (
    AircraftParameters,
    CaseParameters,
    FlowParameters,
    MeshMode,
    MeshParameters,
    OutputParameters,
    ReferenceParameters,
    SolverParameters,
)

from phoenix_aero_lite.utilities.environment import (
    collect_environment,
    format_environment_report,
)


def main(argv: list[str] | None = None) -> int:
    """Run a headless case or print read-only workstation diagnostics."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "run-case":
        return run_case(arguments[1:])
    if arguments and arguments[0] == "grid-study":
        return run_grid_study(arguments[1:])
    if arguments and arguments[0] == "benchmark-audit":
        return run_benchmark_audit(arguments[1:])
    print("\n".join(format_environment_report(collect_environment())))
    return 0


def run_benchmark_audit(argv: list[str]) -> int:
    """Audit an immutable SU2 evidence directory as L1 regression evidence."""

    parser = argparse.ArgumentParser(prog="pal benchmark-audit")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        root = args.evidence_dir.resolve(strict=True)
        required = {
            name: (root / name).resolve(strict=True)
            for name in ("exit_code.txt", "history.csv", "stdout.txt", "stderr.txt", "provenance.json")
        }
        if any(path.parent != root for path in required.values()):
            raise ValueError("BENCHMARK_EVIDENCE_PATH_INVALID")
        process_exit_code = int(required["exit_code.txt"].read_text(encoding="utf-8-sig").strip())
        history_text = required["history.csv"].read_text(encoding="utf-8-sig")
        stdout = _read_text_auto(required["stdout.txt"])
        provenance = json.loads(required["provenance.json"].read_text(encoding="utf-8-sig"))
        origin = str(provenance.get("su2_config_origin", ""))
        official_source = origin.rstrip("/").casefold() in {
            "https://github.com/su2code/su2.git",
            "https://github.com/su2code/su2",
        }
        convergence_matches = re.findall(
            r"\|\s*rms\[P\]\s*\|[^\n]*\|\s*(Yes|No)\s*\|",
            stdout,
            flags=re.IGNORECASE,
        )
        convergence = (
            "converged"
            if convergence_matches and convergence_matches[-1].casefold() == "yes"
            else "not_converged"
        )
        final_cl, final_cd = _final_screen_forces(stdout)
        has_nonfinite = bool(re.search(r"(?<![A-Za-z])(nan|[+-]?inf)(?![A-Za-z])", history_text, re.IGNORECASE))
        execution_passed = (
            process_exit_code == 0
            and bool(history_text.strip())
            and not has_nonfinite
            and "Exit Success (SU2_CFD)" in stdout
        )
        payload = {
            "schema_version": 1,
            "evidence_directory": root.name,
            "official_source": official_source,
            "source_origin": origin,
            "process_exit_code": process_exit_code,
            "execution_passed": execution_passed,
            "history_nonfinite": has_nonfinite,
            "convergence_status": convergence,
            "final_cl": final_cl,
            "final_cd": final_cd,
            "validation_level": "L1" if official_source else None,
            "validation_kind": "official_software_regression" if official_source else "unverified_source",
            "engineering_validation": False,
            "limitations": [
                "Process success is independent from numerical convergence.",
                "L1 regression evidence is not agreement with public experimental data.",
            ],
            "sha256": {name: _sha256(path) for name, path in required.items()},
        }
        _write_json_atomic(args.output.resolve(strict=False), payload)
        print(json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True))
        return 0 if execution_passed and convergence == "converged" and official_source else 3
    except SystemExit:
        return 2
    except Exception as error:
        output = _grid_output_from_argv(argv)
        payload = {"schema_version": 1, "status": "failed", "error_code": str(error) or type(error).__name__}
        if output is not None:
            _write_json_atomic(output, payload)
        print(json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True))
        return 2


def _final_screen_forces(stdout: str) -> tuple[float | None, float | None]:
    final: tuple[float, float] | None = None
    pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*[+-]?[\d.]+(?:[Ee][+-]?\d+)?\s*\|"
        r"\s*[+-]?[\d.]+(?:[Ee][+-]?\d+)?\s*\|\s*[+-]?[\d.]+(?:[Ee][+-]?\d+)?\s*\|"
        r"\s*([+-]?[\d.]+(?:[Ee][+-]?\d+)?)\s*\|\s*([+-]?[\d.]+(?:[Ee][+-]?\d+)?)\s*\|",
        re.MULTILINE,
    )
    for match in pattern.finditer(stdout):
        final = (float(match.group(1)), float(match.group(2)))
    return final if final is not None else (None, None)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def run_grid_study(argv: list[str]) -> int:
    """Analyze three real case summaries without manufacturing missing evidence."""

    parser = argparse.ArgumentParser(prog="pal grid-study")
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--medium", type=Path, required=True)
    parser.add_argument("--fine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        levels = tuple(
            _load_grid_level(path.resolve(strict=True), expected_level)
            for path, expected_level in (
                (args.coarse, "coarse"),
                (args.medium, "medium"),
                (args.fine, "fine"),
            )
        )
        quantities = analyze_aerodynamic_grid_study(
            coarse=levels[0], medium=levels[1], fine=levels[2]
        )
        computable = all(item.gci_computable for item in quantities.values())
        payload = {
            "schema_version": 1,
            "status": "computed" if computable else "blocked",
            "inputs": [
                {"file": path.name, "sha256": _sha256(path.resolve(strict=True))}
                for path in (args.coarse, args.medium, args.fine)
            ],
            "quantities": {name: result.to_dict() for name, result in quantities.items()},
        }
        _write_json_atomic(args.output.resolve(strict=False), payload)
        print(json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True))
        return 0 if computable else 3
    except SystemExit:
        return 2
    except Exception as error:
        payload = {
            "schema_version": 1,
            "status": "failed",
            "error_code": str(error).strip() or type(error).__name__,
            "error_type": type(error).__name__,
        }
        output = _grid_output_from_argv(argv)
        if output is not None:
            _write_json_atomic(output, payload)
        print(json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True))
        return 2


def _load_grid_level(path: Path, expected_level: str) -> AerodynamicGridLevel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("level") != expected_level:
        raise ValueError("GRID_LEVEL_INPUT_INVALID")
    return AerodynamicGridLevel(
        level=expected_level,
        node_count=payload["node_count"],
        cell_count=payload["cell_count"],
        cl=payload["cl"],
        cd=payload["cd"],
        convergence_status=payload["convergence_status"],
        common_setup_fingerprint=payload["common_setup_fingerprint"],
        elapsed_seconds=payload["elapsed_seconds"],
        spatial_dimension=payload.get("spatial_dimension", 3),
    )


def _grid_output_from_argv(argv: list[str]) -> Path | None:
    try:
        return Path(argv[argv.index("--output") + 1]).resolve(strict=False)
    except (ValueError, IndexError):
        return None


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_case(
    argv: list[str],
    *,
    pipeline_factory: Callable[..., PhoenixCasePipeline] = PhoenixCasePipeline,
) -> int:
    """Run the audited Preview pipeline without constructing a GUI."""

    parser = _run_case_parser()
    summary_path = _summary_path_from_argv(argv)
    try:
        args = parser.parse_args(argv)
        summary_path = args.summary_json.resolve(strict=False)
        source = args.step.resolve(strict=False)
        su2 = args.su2.resolve(strict=False)
        if not source.is_file() or not su2.is_file():
            raise FileNotFoundError("HEADLESS_INPUT_NOT_FOUND")
        if source.suffix.casefold() not in {".step", ".stp"}:
            raise ValueError("MODEL_MUST_BE_STEP")
        parameters = CaseParameters(
            flow=FlowParameters(args.velocity, 1.225, 1.7894e-5, args.angle),
            reference=ReferenceParameters(args.s_ref, args.c_ref),
            aircraft=AircraftParameters(args.mass),
            mesh=MeshParameters(MeshMode.PREVIEW, args.target_size),
            solver=SolverParameters(args.iterations),
            output=OutputParameters(args.output.resolve(strict=False)),
        )
        if parameters.validate():
            raise ValueError("HEADLESS_PARAMETERS_INVALID")
        pipeline = pipeline_factory(
            su2_cfd_executable=su2,
            software_versions=_software_versions(args.su2_version),
            solver_timeout_s=args.timeout,
        )
        result = pipeline.run(source, parameters, args.output.resolve(strict=False))
        convergence = result.context["convergence"]
        credibility = assess_credibility(
            convergence, result.context.get("mesh_quality")
        )
        payload = {
            "workflow_status": "completed",
            "execution_status": "completed",
            "convergence_status": convergence.status.value,
            "reason_code": convergence.reason_code,
            "credibility": credibility.level.value,
            "credibility_reason_codes": list(credibility.reason_codes),
            "coefficients_usable": credibility.coefficients_usable,
            "fingerprint": result.fingerprint,
            "case_root": str(result.case_root.resolve(strict=False)),
            "manifest": str(result.manifest_path.resolve(strict=False)),
            "history_csv": _context_path(result.context, "history_path"),
            "flow_vtu": _context_path(result.context, "flow_vtu"),
            "report_html": _context_path(result.context, "report_path"),
            "executed_steps": list(result.executed_steps),
            "reused_steps": list(result.reused_steps),
        }
        _publish_summary(summary_path, payload)
        return 0
    except SystemExit:
        payload = {
            "workflow_status": "failed",
            "execution_status": "failed",
            "error_code": "HEADLESS_ARGUMENTS_INVALID",
        }
    except FileNotFoundError:
        payload = {
            "workflow_status": "failed",
            "execution_status": "failed",
            "error_code": "HEADLESS_INPUT_NOT_FOUND",
        }
    except Exception as error:
        code = str(error).strip() or type(error).__name__
        payload = {
            "workflow_status": "failed",
            "execution_status": "failed",
            "error_code": code,
            "error_type": type(error).__name__,
        }
    _publish_summary(summary_path, payload)
    return 2


def _run_case_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PhoenixAeroLite run-case")
    parser.add_argument("--step", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--su2", type=Path, required=True)
    parser.add_argument("--velocity", type=float, default=15.0)
    parser.add_argument("--angle", type=float, default=6.0)
    parser.add_argument("--s-ref", type=float, default=1.0)
    parser.add_argument("--c-ref", type=float, default=1.0)
    parser.add_argument("--mass", type=float, default=1.0)
    parser.add_argument("--target-size", type=float, default=0.5)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--su2-version", default="8.5.0")
    parser.add_argument("--summary-json", type=Path, required=True)
    return parser


def _software_versions(su2_version: str) -> dict[str, str]:
    return {
        "Phoenix Aero Lite": _distribution_version("phoenix-aero-lite"),
        "Gmsh": _distribution_version("gmsh"),
        "SU2": su2_version,
        "meshio": _distribution_version("meshio"),
        "PyVista": _distribution_version("pyvista"),
    }


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        module_name = name.replace("-", "_")
        try:
            module = __import__(module_name)
        except ImportError:
            return "unknown"
        return str(getattr(module, "__version__", "unknown"))


def _context_path(context, key: str) -> str:
    return str(Path(context[key]).resolve(strict=False))


def _summary_path_from_argv(argv: list[str]) -> Path | None:
    try:
        index = argv.index("--summary-json")
        return Path(argv[index + 1]).resolve(strict=False)
    except (ValueError, IndexError):
        return None


def _publish_summary(path: Path | None, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(encoded + "\n", encoding="utf-8")
        temporary.replace(path)
    if sys.stdout is not None:
        print(encoded)
