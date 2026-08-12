from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from PIL import Image

from phoenix_aero_lite.models.evidence import ExecutionStatus
from phoenix_aero_lite.models.results import AerodynamicSummary, DerivedQuantity
from phoenix_aero_lite.reporting.charts import generate_convergence_chart
from phoenix_aero_lite.reporting.html_report import (
    ReportData,
    generate_html_report,
)
from phoenix_aero_lite.solver.convergence import (
    ConvergenceResult,
    ConvergenceStatus,
    ConvergenceThresholds,
)
from phoenix_aero_lite.solver.su2_history import HistorySample, Su2History
from phoenix_aero_lite.solver.credibility import assess_credibility
from phoenix_aero_lite.utilities.process_runner import (
    ProcessResult,
    ProcessStatus,
)


def _history() -> Su2History:
    return Su2History(
        source_path=None,
        samples=tuple(
            HistorySample(i, -1.0 - i, -2.0 - i, -3.0 - i, 0.03, 0.5, 0, 0, 0)
            for i in range(6)
        ),
    )


def _convergence(status: ConvergenceStatus) -> ConvergenceResult:
    return ConvergenceResult(
        status=status,
        reason_code="TARGET_AND_FORCE_PLATEAU",
        iterations_observed=6,
        final_residual=-6,
        final_cl=0.5,
        final_cd=0.03,
        thresholds=ConvergenceThresholds(5, -5, 3, 3, 0.01, 2, 0.05, 100),
    )


def _aero(valid: bool) -> AerodynamicSummary:
    q = DerivedQuantity(245.0, "Pa", "0.5*rho*V^2")
    weight = DerivedQuantity(98.0665, "N", "mass*g")
    value = DerivedQuantity(245.0, "N", "CL*q*S") if valid else None
    return AerodynamicSummary(
        valid=valid,
        reason_code="ok" if valid else "CFD_NOT_CONVERGED",
        cl=DerivedQuantity(0.5, "1", "SU2 CL"),
        cd=DerivedQuantity(0.03, "1", "SU2 CD"),
        body_to_wind_drag_coefficient=None,
        body_to_wind_lift_coefficient=None,
        dynamic_pressure=q,
        lift=value,
        drag=DerivedQuantity(14.7, "N", "CD*q*S") if valid else None,
        weight=weight,
        lift_margin=DerivedQuantity(146.9335, "N", "L-W") if valid else None,
        lift_to_weight_ratio=DerivedQuantity(2.49, "1", "L/W") if valid else None,
        meets_weight_requirement=True if valid else None,
    )


def _process(tmp_path: Path) -> ProcessResult:
    stdout = tmp_path / "stdout.bin"
    stderr = tmp_path / "stderr.bin"
    stdout.write_bytes(b"solver output")
    stderr.write_bytes(b"")
    now = datetime.now(timezone.utc)
    return ProcessResult(
        argv=("C:\\Tools\\SU2_CFD.exe", "-t", "1", "case.cfg"),
        exit_code=0,
        status=ProcessStatus.SUCCEEDED,
        started_at=now,
        ended_at=now,
        cwd=tmp_path,
        environment_delta=MappingProxyType({}),
        stdout_path=stdout,
        stderr_path=stderr,
    )


def test_chart_and_offline_report_include_required_traceability(tmp_path: Path):
    chart = generate_convergence_chart(_history(), tmp_path / "chart.png")
    assert chart.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    screenshot = tmp_path / "view.png"
    Image.new("RGB", (8, 8), "navy").save(screenshot)
    data = ReportData(
        case_name='机翼 <script>alert("x")</script>',
        input_sha256="a" * 64,
        software_versions=MappingProxyType({"SU2": "8.5.0", "Gmsh": "4.15.2"}),
        mesh_quality=MappingProxyType({"minimum_quality": 0.2}),
        process=_process(tmp_path),
        convergence=_convergence(ConvergenceStatus.CONVERGED),
        aerodynamics=_aero(True),
        history=_history(),
        warnings=("仅用于测试",),
        screenshot_path=screenshot,
    )
    report = generate_html_report(data, tmp_path / "report")
    html = report.read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "a" * 64 in html
    assert "SU2_CFD.exe" in html
    assert "TARGET_AND_FORCE_PLATEAU" in html
    assert "data:image/png;base64," in html
    assert "https://" not in html and "http://" not in html


def test_unconverged_report_has_prominent_invalid_banner_and_no_pass_claim(
    tmp_path: Path,
):
    convergence = _convergence(ConvergenceStatus.STAGNATED)
    evidence = assess_credibility(
        convergence,
        MappingProxyType({"near_wall": {"drag_fidelity": "preview_only"}}),
        execution_status=ExecutionStatus.COMPLETED,
    ).scientific_evidence
    data = ReportData(
        case_name="未收敛",
        input_sha256="b" * 64,
        software_versions=MappingProxyType({"SU2": "8.5.0"}),
        mesh_quality=MappingProxyType({"minimum_quality": 0.1}),
        process=_process(tmp_path),
        convergence=convergence,
        aerodynamics=_aero(False),
        history=_history(),
        warnings=("残差停滞",),
        screenshot_path=None,
        scientific_evidence=evidence,
    )
    html = generate_html_report(data, tmp_path / "report").read_text(
        encoding="utf-8"
    )
    assert "当前结果未满足工程结论证据门槛" in html
    assert "非工程用途 CL / CD" in html
    assert "0.5 / 0.03" in html
    assert "diagnostic_only" in html
    assert "stagnated" in html
    assert "validation_level: unassigned" in html
    assert "满足重量要求" not in html
