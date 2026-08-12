"""Generate an offline, traceable Chinese CFD report bundle."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from phoenix_aero_lite.models.evidence import (
    ConvergenceStatus as EvidenceConvergenceStatus,
    ExecutionStatus,
    ScientificEvidence,
    ScientificUseLevel,
)
from phoenix_aero_lite.models.results import AerodynamicSummary
from phoenix_aero_lite.reporting.charts import generate_convergence_chart
from phoenix_aero_lite.solver.convergence import (
    ConvergenceResult,
    ConvergenceStatus,
)
from phoenix_aero_lite.solver.su2_history import Su2History
from phoenix_aero_lite.utilities.process_runner import ProcessResult


_TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[1] / "templates" / "report"
_MAX_EMBED_BYTES = 5 * 1024 * 1024


class HtmlReportError(ValueError):
    """Stable report generation failure."""


@dataclass(frozen=True, slots=True)
class ReportData:
    """Explicit inputs required by the traceable report."""

    case_name: str
    input_sha256: str
    software_versions: Mapping[str, str]
    mesh_quality: Mapping[str, object]
    process: ProcessResult
    convergence: ConvergenceResult
    aerodynamics: AerodynamicSummary
    history: Su2History
    warnings: tuple[str, ...]
    screenshot_path: Path | None
    scientific_evidence: ScientificEvidence | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.case_name, str)
            or not self.case_name
            or not isinstance(self.input_sha256, str)
            or len(self.input_sha256) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in self.input_sha256)
            or not isinstance(self.process, ProcessResult)
            or not isinstance(self.convergence, ConvergenceResult)
            or not isinstance(self.aerodynamics, AerodynamicSummary)
            or not isinstance(self.history, Su2History)
            or (
                self.scientific_evidence is not None
                and not isinstance(self.scientific_evidence, ScientificEvidence)
            )
        ):
            raise HtmlReportError("REPORT_DATA_INVALID")
        try:
            versions = dict(self.software_versions)
            mesh_quality = dict(self.mesh_quality)
            warnings = tuple(self.warnings)
        except (TypeError, ValueError):
            raise HtmlReportError("REPORT_DATA_INVALID") from None
        if (
            any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
                for key, value in versions.items()
            )
            or any(not isinstance(warning, str) for warning in warnings)
        ):
            raise HtmlReportError("REPORT_DATA_INVALID")
        object.__setattr__(
            self,
            "software_versions",
            MappingProxyType(versions),
        )
        object.__setattr__(
            self,
            "mesh_quality",
            MappingProxyType(mesh_quality),
        )
        object.__setattr__(self, "warnings", warnings)


def generate_html_report(data: ReportData, output_directory: Path) -> Path:
    """Build a self-contained report directory and atomically publish it."""

    if not isinstance(data, ReportData):
        raise HtmlReportError("REPORT_DATA_INVALID")
    output, staging = _prepare_transaction(output_directory)
    chart_path = generate_convergence_chart(
        data.history, staging / "convergence.png"
    )
    chart_uri = _image_data_uri(chart_path)
    screenshot_uri = (
        _image_data_uri(data.screenshot_path)
        if data.screenshot_path is not None
        else None
    )
    evidence = data.scientific_evidence or ScientificEvidence(
        execution_status=ExecutionStatus.COMPLETED,
        convergence_status=EvidenceConvergenceStatus(data.convergence.status.value),
        blocking_reasons=("SCIENTIFIC_EVIDENCE_MISSING",),
    )
    engineering_use = evidence.scientific_use_level in {
        ScientificUseLevel.ENGINEERING_COMPARISON,
        ScientificUseLevel.EXTERNALLY_VALIDATED,
    }
    context = {
        "case_name": data.case_name,
        "input_sha256": data.input_sha256.lower(),
        "software_versions": tuple(sorted(data.software_versions.items())),
        "mesh_quality_json": _strict_json(dict(data.mesh_quality)),
        "argv": data.process.argv,
        "cwd": str(data.process.cwd),
        "exit_code": data.process.exit_code,
        "process_status": data.process.status.value,
        "started_at": data.process.started_at.isoformat(),
        "ended_at": data.process.ended_at.isoformat(),
        "stdout_path": str(data.process.stdout_path),
        "stderr_path": str(data.process.stderr_path),
        "convergence_status": data.convergence.status.value,
        "convergence_reason": data.convergence.reason_code,
        "execution_status": evidence.execution_status.value,
        "scientific_use_level": evidence.scientific_use_level.value,
        "validation_level": (
            evidence.validation_level.value if evidence.validation_level else "unassigned"
        ),
        "quantity_evidence_json": _strict_json(
            {
                name: quantity.to_dict()
                for name, quantity in evidence.quantities.items()
            }
        ),
        "convergence_thresholds_json": _strict_json(
            asdict(data.convergence.thresholds)
        ),
        "aero": data.aerodynamics.to_dict(),
        "valid": (
            data.convergence.status is ConvergenceStatus.CONVERGED
            and data.aerodynamics.valid
            and engineering_use
        ),
        "warnings": data.warnings,
        "chart_uri": chart_uri,
        "screenshot_uri": screenshot_uri,
    }
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIRECTORY),
        autoescape=select_autoescape(("html", "j2")),
        undefined=StrictUndefined,
        newline_sequence="\n",
        keep_trailing_newline=True,
    )
    rendered = environment.get_template("report_zh.html.j2").render(**context)
    try:
        with (staging / "report.html").open(
            "x", encoding="utf-8", newline="\n"
        ) as destination:
            destination.write(rendered)
        os.rename(staging, output)
    except FileExistsError:
        raise HtmlReportError("REPORT_OUTPUT_COLLISION") from None
    except OSError:
        raise HtmlReportError("REPORT_WRITE_FAILED") from None
    return (output / "report.html").resolve(strict=True)


def _prepare_transaction(output_directory: Path) -> tuple[Path, Path]:
    if (
        not isinstance(output_directory, Path)
        or not output_directory.name
        or ".." in output_directory.parts
    ):
        raise HtmlReportError("REPORT_OUTPUT_UNSAFE")
    requested = (
        output_directory
        if output_directory.is_absolute()
        else Path.cwd() / output_directory
    )
    _reject_redirecting_ancestors(requested.parent)
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    if output.exists():
        raise HtmlReportError("REPORT_OUTPUT_COLLISION")
    staging = parent / f".{requested.name}.staging-{uuid4().hex}"
    try:
        staging.mkdir()
    except OSError:
        raise HtmlReportError("REPORT_WRITE_FAILED") from None
    return output, staging


def _image_data_uri(path: Path) -> str:
    if not isinstance(path, Path) or not path.is_file():
        raise HtmlReportError("REPORT_IMAGE_MISSING")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_EMBED_BYTES:
        raise HtmlReportError("REPORT_IMAGE_SIZE_INVALID")
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HtmlReportError("REPORT_IMAGE_INVALID")
    return "data:image/png;base64," + base64.b64encode(raw).decode(
        "ascii"
    )


def _strict_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    except (TypeError, ValueError):
        raise HtmlReportError("REPORT_DATA_INVALID") from None


def _reject_redirecting_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and (
            current.is_symlink()
            or (hasattr(current, "is_junction") and current.is_junction())
        ):
            raise HtmlReportError("REPORT_OUTPUT_UNSAFE")
        if current.parent == current:
            return
        current = current.parent
