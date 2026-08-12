"""Production composition of the reusable Phoenix Aero Lite CFD adapters."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from types import MappingProxyType
from typing import Callable, Mapping
from uuid import uuid4

from phoenix_aero_lite import __version__
from phoenix_aero_lite.app.case_workspace import stage_step
from phoenix_aero_lite.app.workflow import (
    ResumableWorkflow,
    StepOutcome,
    WorkflowRunResult,
    WorkflowStepDefinition,
)
from phoenix_aero_lite.geometry.gmsh_geometry import GmshGeometryAdapter
from phoenix_aero_lite.meshing.gmsh_mesher import GmshMesher
from phoenix_aero_lite.models.geometry import BoundingBox
from phoenix_aero_lite.models.mesh import PhysicalGroupSummary
from phoenix_aero_lite.models.parameters import CaseParameters
from phoenix_aero_lite.postprocess.aero_summary import summarize_aerodynamics
from phoenix_aero_lite.postprocess.pyvista_results import load_result
from phoenix_aero_lite.postprocess.y_plus import (
    analyze_y_plus_surface,
    merge_y_plus_evidence,
)
from phoenix_aero_lite.reporting.html_report import ReportData, generate_html_report
from phoenix_aero_lite.solver.convergence import (
    ConvergenceExecution,
    ConvergenceStatus,
    classify_convergence,
    convergence_policy,
)
from phoenix_aero_lite.solver.credibility import assess_credibility
from phoenix_aero_lite.solver.su2_config import render_su2_config
from phoenix_aero_lite.solver.su2_history import history_is_complete, parse_history_csv
from phoenix_aero_lite.utilities.process_runner import (
    CancellationToken,
    ProcessResult,
    ProcessStatus,
    run_process,
)
from phoenix_aero_lite.utilities.source_guard import sha256_file


class PipelineError(RuntimeError):
    """Stable production pipeline failure."""


_PIPELINE_CACHE_SCHEMA_ID = "phoenix-pipeline-cache-v2"
_STAGE_IMPLEMENTATION_VERSIONS = MappingProxyType(
    {
        "stage": "stage-v2",
        "inspect": "gmsh-occ-inspection-v2",
        "mesh": "external-flow-near-wall-v4",
        "config": "su2-inc-rans-sst-v3",
        "solve": "su2-process-contract-v2",
        "parse": "convergence-y-plus-v3",
        "visualize": "pyvista-offscreen-v2",
        "report": "report-zh-v3",
    }
)


class PhoenixCasePipeline:
    """Run or resume the real Gmsh → SU2 → PyVista → report pipeline."""

    def __init__(
        self,
        *,
        su2_cfd_executable: Path,
        software_versions: Mapping[str, str],
        solver_timeout_s: float | None = None,
    ) -> None:
        executable = Path(su2_cfd_executable)
        if (
            not executable.is_absolute()
            or not executable.is_file()
            or executable.name.casefold() != "su2_cfd.exe"
        ):
            raise PipelineError("PIPELINE_SU2_INVALID")
        self._su2 = executable.resolve(strict=True)
        self._versions = MappingProxyType(dict(software_versions))
        self._solver_timeout_s = solver_timeout_s

    def run(
        self,
        source_step: Path,
        parameters: CaseParameters,
        case_root: Path,
        *,
        cancellation: CancellationToken | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
        producer_id: str | None = None,
    ) -> WorkflowRunResult:
        """Run all eight ordered stages with hash-based crash recovery."""

        if not isinstance(parameters, CaseParameters) or parameters.validate():
            raise PipelineError("PIPELINE_PARAMETERS_INVALID")
        source = Path(source_step).resolve(strict=True)
        fingerprint = _case_fingerprint(
            source, parameters, self._versions, self._su2
        )
        workflow_identity = _workflow_identity(source, self._versions, self._su2)
        stage_fingerprints = _pipeline_stage_fingerprints(
            source, parameters, self._versions, self._su2
        )
        run_root = Path(case_root).resolve(strict=False) / "runs" / workflow_identity[:16]
        token = cancellation or CancellationToken()
        steps = self._build_steps(
            source,
            parameters,
            run_root,
            token,
            fingerprint,
            stage_fingerprints,
        )
        progress_by_step = {
            "stage": 12,
            "inspect": 18,
            "mesh": 30,
            "config": 50,
            "solve": 60,
            "parse": 86,
            "visualize": 92,
            "report": 96,
        }

        def report_step(name: str, status: str) -> None:
            if progress_callback is None:
                return
            progress = progress_by_step[name]
            if status in {"complete", "reused"}:
                progress = min(99, progress + 3)
            progress_callback(name, progress)

        return ResumableWorkflow(run_root, steps).run(
            workflow_identity,
            on_step=report_step,
            producer_id=producer_id,
            provenance=_case_provenance(
                source=source,
                parameters=parameters,
                versions=self._versions,
                su2=self._su2,
            ),
        )

    def cache_run_root(
        self,
        source_step: Path,
        parameters: CaseParameters,
        cache_root: Path,
    ) -> Path:
        """Return the shared run path so callers can lease it before access."""

        if not isinstance(parameters, CaseParameters) or parameters.validate():
            raise PipelineError("PIPELINE_PARAMETERS_INVALID")
        source = Path(source_step).resolve(strict=True)
        workflow_identity = _workflow_identity(source, self._versions, self._su2)
        return Path(cache_root).resolve(strict=False) / "runs" / workflow_identity[:16]

    def _build_steps(
        self,
        source: Path,
        parameters: CaseParameters,
        run_root: Path,
        token: CancellationToken,
        fingerprint: str,
        stage_fingerprints: Mapping[str, str],
    ) -> tuple[WorkflowStepDefinition, ...]:
        def stage(context):
            staged_path = run_root / "input" / "model.step"
            if staged_path.is_file() and sha256_file(staged_path) == sha256_file(
                source
            ):
                staged = staged_path
            else:
                staged = stage_step(source, run_root).staged_path
            return StepOutcome(
                (staged,),
                {"source_path": str(source), "source_sha256": sha256_file(source)},
            )

        def restore_stage(context, record):
            context["staged_path"] = Path(record.artifacts[0].path)

        def inspect(context):
            inspection = GmshGeometryAdapter().inspect_step(
                context["staged_path"]
            )
            payload = {
                "volume_count": inspection.volume_count,
                "surface_count": inspection.surface_count,
                "bounding_box_min_m": list(inspection.bounding_box_min_m),
                "bounding_box_max_m": list(inspection.bounding_box_max_m),
                "dimensions_m": list(inspection.dimensions_m),
                "unit": inspection.unit,
                "scale_note": inspection.scale_note,
            }
            path = run_root / "geometry" / "inspection.json"
            _write_json_atomic(path, payload)
            return StepOutcome((path,), payload)

        def mesh(context):
            output = run_root / f"mesh-{uuid4().hex}"
            artifacts = GmshMesher(
                su2_validator_path=self._su2
            ).build_external_mesh(
                context["staged_path"],
                parameters.mesh,
                output,
                flow_parameters=parameters.flow,
                reference_parameters=parameters.reference,
            )
            metadata = {
                "physical_groups": [
                    group.to_dict() for group in artifacts.physical_groups
                ],
                "quality": artifacts.quality.to_dict(),
            }
            return StepOutcome(
                (
                    artifacts.msh_path,
                    artifacts.su2_path,
                    artifacts.vtu_path,
                    artifacts.mapping_json_path,
                    artifacts.quality_json_path,
                ),
                metadata,
            )

        def restore_mesh(context, record):
            by_suffix = {Path(item.path).suffix.lower(): Path(item.path) for item in record.artifacts}
            context["mesh_su2"] = by_suffix[".su2"]
            context["mesh_vtu"] = by_suffix[".vtu"]
            context["mesh_quality"] = dict(record.metadata["quality"])
            context["physical_groups"] = tuple(
                _physical_group_from_dict(item)
                for item in record.metadata["physical_groups"]
            )

        def config(context):
            output = run_root / f"solver-{uuid4().hex}"
            rendered = render_su2_config(
                parameters,
                context["mesh_su2"],
                context["physical_groups"],
                output,
            )
            mesh_copy = output / "mesh.su2"
            return StepOutcome(
                (rendered.path, mesh_copy),
                {
                    "config_sha256": rendered.sha256,
                    "normalized_values": dict(rendered.normalized_values),
                },
            )

        def restore_config(context, record):
            context["config_path"] = next(
                Path(item.path)
                for item in record.artifacts
                if Path(item.path).suffix.lower() == ".cfg"
            )

        def solve(context):
            config_path = context["config_path"]
            audit = run_root / "audit" / f"solve-{uuid4().hex}"
            result = run_process(
                [str(self._su2), "-t", "1", config_path.name],
                cwd=config_path.parent,
                audit_directory=audit,
                timeout_s=self._solver_timeout_s,
                cancellation=token,
            )
            if result.status is not ProcessStatus.SUCCEEDED:
                raise PipelineError(f"PIPELINE_SOLVE_{result.status.value.upper()}")
            required = (
                config_path.parent / "history.csv",
                config_path.parent / "restart_flow.dat",
                config_path.parent / "flow.vtu",
                config_path.parent / "surface_flow.vtu",
                result.stdout_path,
                result.stderr_path,
            )
            if any(not path.is_file() or path.stat().st_size <= 0 for path in required[:4]):
                raise PipelineError("PIPELINE_SOLVE_OUTPUT_MISSING")
            metadata = {
                "argv": list(result.argv),
                "exit_code": result.exit_code,
                "status": result.status.value,
                "started_at": result.started_at.isoformat(),
                "ended_at": result.ended_at.isoformat(),
                "cwd": str(result.cwd),
                "stdout_path": str(result.stdout_path),
                "stderr_path": str(result.stderr_path),
            }
            return StepOutcome(required, metadata)

        def restore_solve(context, record):
            metadata = record.metadata
            context["process_result"] = ProcessResult(
                argv=tuple(metadata["argv"]),
                exit_code=metadata["exit_code"],
                status=ProcessStatus(metadata["status"]),
                started_at=datetime.fromisoformat(metadata["started_at"]),
                ended_at=datetime.fromisoformat(metadata["ended_at"]),
                cwd=Path(metadata["cwd"]),
                environment_delta=MappingProxyType({}),
                stdout_path=Path(metadata["stdout_path"]),
                stderr_path=Path(metadata["stderr_path"]),
            )
            for artifact in record.artifacts:
                name = Path(artifact.path).name
                if name == "history.csv":
                    context["history_path"] = Path(artifact.path)
                elif name == "flow.vtu":
                    context["flow_vtu"] = Path(artifact.path)
                elif name == "surface_flow.vtu":
                    context["surface_flow_vtu"] = Path(artifact.path)

        def parse(context):
            history = parse_history_csv(context["history_path"])
            policy = convergence_policy(
                parameters.mesh.mode.value, parameters.solver.max_iterations
            )
            execution = _convergence_execution(
                context["process_result"], context["history_path"]
            )
            convergence = classify_convergence(
                history, policy, execution=execution
            )
            y_plus = analyze_y_plus_surface(
                context["surface_flow_vtu"], target_range=(0.0, 1.0)
            )
            context["mesh_quality"] = merge_y_plus_evidence(
                context.get("mesh_quality"), y_plus
            )
            credibility = assess_credibility(
                convergence, context.get("mesh_quality")
            )
            summary = summarize_aerodynamics(
                parameters, convergence, history.samples[-1]
            )
            convergence_path = run_root / "postprocess" / "convergence.json"
            evidence_path = run_root / "postprocess" / "scientific_evidence.json"
            y_plus_path = run_root / "postprocess" / "y_plus.json"
            result_path = run_root / "postprocess" / "aerodynamics.json"
            _write_json_atomic(
                convergence_path,
                {
                    "status": convergence.status.value,
                    "reason_code": convergence.reason_code,
                    "iterations_observed": convergence.iterations_observed,
                    "final_residual": convergence.final_residual,
                    "final_cl": convergence.final_cl,
                    "final_cd": convergence.final_cd,
                    "policy_version": convergence.policy_version,
                    "execution": {
                        "process_status": execution.process_status,
                        "exit_code": execution.exit_code,
                        "history_complete": execution.history_complete,
                        "integrity_error": execution.integrity_error,
                    },
                    "diagnostics": dict(convergence.diagnostics),
                    "thresholds": {
                        field: getattr(policy, field)
                        for field in policy.__dataclass_fields__
                    },
                },
            )
            _write_json_atomic(
                evidence_path, credibility.scientific_evidence.to_dict()
            )
            _write_json_atomic(y_plus_path, y_plus.to_dict())
            _write_json_atomic(result_path, summary.to_dict())
            return StepOutcome(
                (convergence_path, evidence_path, y_plus_path, result_path),
                {
                    "convergence_status": convergence.status.value,
                    "convergence_reason": convergence.reason_code,
                    "scientific_use_level": (
                        credibility.scientific_evidence.scientific_use_level.value
                    ),
                },
            )

        def restore_parse(context, _record):
            history = parse_history_csv(context["history_path"])
            policy = convergence_policy(
                parameters.mesh.mode.value, parameters.solver.max_iterations
            )
            convergence = classify_convergence(
                history,
                policy,
                execution=_convergence_execution(
                    context["process_result"], context["history_path"]
                ),
            )
            context["history"] = history
            context["convergence"] = convergence
            y_plus = analyze_y_plus_surface(
                context["surface_flow_vtu"], target_range=(0.0, 1.0)
            )
            context["mesh_quality"] = merge_y_plus_evidence(
                context.get("mesh_quality"), y_plus
            )
            context["credibility"] = assess_credibility(
                convergence, context.get("mesh_quality")
            )
            context["aerodynamics"] = summarize_aerodynamics(
                parameters, convergence, history.samples[-1]
            )

        def visualize(context):
            output = run_root / "postprocess" / f"flow-{uuid4().hex}.png"
            load_result(context["flow_vtu"]).screenshot(output)
            return StepOutcome((output,), {})

        def restore_visualize(context, record):
            context["screenshot_path"] = Path(record.artifacts[0].path)

        def report(context):
            warnings = []
            if parameters.mesh.mode.value == "preview":
                warnings.append("Preview 网格仅用于流程烟测，CD 不是最终工程精度。")
            if context["convergence"].status is not ConvergenceStatus.CONVERGED:
                warnings.append("CFD 未通过收敛判据，气动力和重量结论无效。")
            data = ReportData(
                case_name=Path(source).stem,
                input_sha256=sha256_file(source),
                software_versions=self._versions,
                mesh_quality=context["mesh_quality"],
                process=context["process_result"],
                convergence=context["convergence"],
                aerodynamics=context["aerodynamics"],
                history=context["history"],
                warnings=tuple(warnings),
                screenshot_path=context["screenshot_path"],
                scientific_evidence=context["credibility"].scientific_evidence,
            )
            report_path = generate_html_report(
                data, run_root / f"report-{uuid4().hex}"
            )
            return StepOutcome((report_path,), {"fingerprint": fingerprint})

        def restore_report(context, record):
            context["report_path"] = Path(record.artifacts[0].path)

        return (
            WorkflowStepDefinition("stage", (), stage, restore_stage, stage_fingerprints["stage"]),
            WorkflowStepDefinition("inspect", ("stage",), inspect, input_fingerprint=stage_fingerprints["inspect"]),
            WorkflowStepDefinition("mesh", ("inspect",), mesh, restore_mesh, stage_fingerprints["mesh"]),
            WorkflowStepDefinition("config", ("mesh",), config, restore_config, stage_fingerprints["config"]),
            WorkflowStepDefinition("solve", ("config",), solve, restore_solve, stage_fingerprints["solve"]),
            WorkflowStepDefinition("parse", ("solve",), parse, restore_parse, stage_fingerprints["parse"]),
            WorkflowStepDefinition("visualize", ("solve",), visualize, restore_visualize, stage_fingerprints["visualize"]),
            WorkflowStepDefinition("report", ("parse", "visualize"), report, restore_report, stage_fingerprints["report"]),
        )


def _case_fingerprint(
    source: Path,
    parameters: CaseParameters,
    versions: Mapping[str, str],
    su2: Path,
) -> str:
    digest = hashlib.sha256()
    digest.update(sha256_file(source).encode("ascii"))
    digest.update(parameters.to_json().encode("utf-8"))
    digest.update(
        json.dumps(dict(versions), sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
    )
    digest.update(sha256_file(su2).encode("ascii"))
    return digest.hexdigest()


def _workflow_identity(
    source: Path,
    versions: Mapping[str, str],
    su2: Path,
    *,
    cache_schema_id: str = _PIPELINE_CACHE_SCHEMA_ID,
) -> str:
    """Stable case identity; stage fingerprints decide parameter invalidation."""

    return _stable_fingerprint(
        {
            "source_sha256": sha256_file(source),
            "cache_schema_id": cache_schema_id,
            "software_version": __version__,
            "versions": dict(versions),
            "su2_sha256": sha256_file(su2),
        }
    )


def _pipeline_stage_fingerprints(
    source: Path,
    parameters: CaseParameters,
    versions: Mapping[str, str],
    su2: Path,
    *,
    implementation_versions: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return content fingerprints matching the real stage dependency DAG."""

    payload = parameters.to_dict()
    implementations = dict(
        _STAGE_IMPLEMENTATION_VERSIONS
        if implementation_versions is None
        else implementation_versions
    )
    if set(implementations) != set(_STAGE_IMPLEMENTATION_VERSIONS) or any(
        not isinstance(value, str) or not value.strip()
        for value in implementations.values()
    ):
        raise ValueError("PIPELINE_IMPLEMENTATION_VERSIONS_INVALID")
    source_key = {
        "source_sha256": sha256_file(source),
        "gmsh": dict(versions).get("Gmsh", "unknown"),
        "pipeline": __version__,
    }
    flow = dict(payload["flow"])
    reference = dict(payload["reference"])
    stage = _stable_fingerprint(
        {
            "source": source_key["source_sha256"],
            "implementation": implementations["stage"],
        }
    )
    inspect = _stable_fingerprint(
        {"geometry": source_key, "implementation": implementations["inspect"]}
    )
    mesh = _stable_fingerprint(
        {
            "geometry": inspect,
            "mesh": payload["mesh"],
            # Near-wall height depends on Reynolds inputs and chord, but not
            # angle of attack or reference area.
            "near_wall_flow": {
                name: flow[name]
                for name in (
                    "velocity_m_s",
                    "density_kg_m3",
                    "dynamic_viscosity_pa_s",
                )
            },
            "near_wall_reference_chord_m": reference["c_ref_m"],
            "implementation": implementations["mesh"],
        }
    )
    config = _stable_fingerprint(
        {
            "mesh": mesh,
            "flow": payload["flow"],
            "reference": payload["reference"],
            "solver": payload["solver"],
            "su2_version": dict(versions).get("SU2", "unknown"),
            "implementation": implementations["config"],
        }
    )
    solve = _stable_fingerprint(
        {
            "config": config,
            "su2_sha256": sha256_file(su2),
            "implementation": implementations["solve"],
        }
    )
    parse = _stable_fingerprint(
        {
            "solve": solve,
            "aircraft": payload["aircraft"],
            "convergence_policy": "phoenix-convergence-v2",
            "y_plus_method": "surface-area-weighted-v1",
            "implementation": implementations["parse"],
        }
    )
    visualize = _stable_fingerprint(
        {
            "solve": solve,
            "pyvista": dict(versions).get("PyVista", "unknown"),
            "scene": "offscreen-summary-v1",
            "implementation": implementations["visualize"],
        }
    )
    report = _stable_fingerprint(
        {
            "parse": parse,
            "visualize": visualize,
            "template": "report-zh-v2",
            "implementation": implementations["report"],
        }
    )
    return {
        "stage": stage,
        "inspect": inspect,
        "mesh": mesh,
        "config": config,
        "solve": solve,
        "parse": parse,
        "visualize": visualize,
        "report": report,
    }


def _stable_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case_provenance(
    *,
    source: Path,
    parameters: CaseParameters,
    versions: Mapping[str, str],
    su2: Path,
) -> dict[str, object]:
    """Capture reproducibility facts without changing the case fingerprint."""

    return {
        "source_sha256": sha256_file(source),
        "derived_sha256": {},
        "software_version": __version__,
        "git_commit": _git_commit(),
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "dependencies": dict(versions),
        "tools": {
            "SU2": dict(versions).get("SU2", "unknown"),
            "SU2_CFD_sha256": sha256_file(su2),
        },
        "cache": {
            "schema_id": _PIPELINE_CACHE_SCHEMA_ID,
            "stage_implementations": dict(_STAGE_IMPLEMENTATION_VERSIONS),
        },
        "user_inputs": parameters.to_dict(),
        "automatic_values": {},
        "user_overrides": {},
        "parameter_sources": {},
        "parent_task_id": None,
        "cache_source": None,
    }


def _git_commit() -> str:
    project_root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = result.stdout.strip()
    return value if len(value) == 40 else "unknown"


def _physical_group_from_dict(payload: Mapping[str, object]) -> PhysicalGroupSummary:
    return PhysicalGroupSummary(
        name=str(payload["name"]),
        dimension=int(payload["dimension"]),
        entity_count=int(payload["entity_count"]),
        bounding_boxes_m=tuple(
            BoundingBox(
                minimum_m=tuple(bounds["minimum_m"]),
                maximum_m=tuple(bounds["maximum_m"]),
            )
            for bounds in payload["bounding_boxes_m"]
        ),
    )


def _convergence_execution(
    process: ProcessResult,
    history_path: Path,
) -> ConvergenceExecution:
    return ConvergenceExecution(
        process_status=process.status.value,
        exit_code=process.exit_code,
        history_complete=history_is_complete(history_path),
    )


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    temporary = path.parent / f".{path.name}.tmp-{uuid4().hex}"
    with temporary.open("xb") as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)
