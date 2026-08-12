import json
from pathlib import Path
from types import SimpleNamespace

from phoenix_aero_lite.cli import main, run_case
from phoenix_aero_lite.models.parameters import MeshMode


def _grid_level(path: Path, *, level: str, cells: int, cl: float, cd: float, status: str = "converged") -> None:
    path.write_text(
        json.dumps(
            {
                "level": level,
                "node_count": cells // 2,
                "cell_count": cells,
                "cl": cl,
                "cd": cd,
                "convergence_status": status,
                "common_setup_fingerprint": "a" * 64,
                "elapsed_seconds": float(cells) / 1000.0,
            }
        ),
        encoding="utf-8",
    )


def test_grid_study_cli_writes_machine_readable_gci(tmp_path: Path):
    inputs = []
    for level, cells, cl, cd in (
        ("coarse", 1000, 0.50, 0.030),
        ("medium", 8000, 0.55, 0.025),
        ("fine", 64000, 0.575, 0.0225),
    ):
        path = tmp_path / f"{level}.json"
        _grid_level(path, level=level, cells=cells, cl=cl, cd=cd)
        inputs.append(path)
    output = tmp_path / "grid-study.json"

    exit_code = main(
        [
            "grid-study",
            "--coarse", str(inputs[0]),
            "--medium", str(inputs[1]),
            "--fine", str(inputs[2]),
            "--output", str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "computed"
    assert payload["quantities"]["CL"]["gci_computable"] is True


def test_grid_study_cli_returns_blocked_when_one_real_run_did_not_converge(tmp_path: Path):
    inputs = []
    for level, cells, status in (
        ("coarse", 1000, "converged"),
        ("medium", 8000, "stagnated"),
        ("fine", 64000, "converged"),
    ):
        path = tmp_path / f"{level}.json"
        _grid_level(path, level=level, cells=cells, cl=0.5 + cells / 1e6, cd=0.03, status=status)
        inputs.append(path)
    output = tmp_path / "grid-study.json"

    exit_code = main(
        [
            "grid-study",
            "--coarse", str(inputs[0]),
            "--medium", str(inputs[1]),
            "--fine", str(inputs[2]),
            "--output", str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 3
    assert payload["status"] == "blocked"
    assert payload["quantities"]["CL"]["blocking_reasons"] == ["GRID_LEVEL_NOT_ITERATIVELY_CONVERGED"]


def test_benchmark_audit_does_not_equate_exit_zero_with_convergence(tmp_path: Path):
    evidence = tmp_path / "official"
    evidence.mkdir()
    (evidence / "exit_code.txt").write_text("0\n", encoding="utf-8-sig")
    (evidence / "history.csv").write_text(
        '"Inner_Iter","rms[P]","rms[k]","rms[w]"\n0,-4,-5,-6\n2499,-7.908,-9.25,-2.72\n',
        encoding="utf-8",
    )
    (evidence / "stdout.txt").write_text(
        "| 2499| -7.908372| -9.252227| -2.724290| -0.000002| 0.007106|\n"
        "| rms[P]| -7.90837| < -10| No|\n"
        "Exit Success (SU2_CFD)\n",
        encoding="utf-16",
    )
    (evidence / "stderr.txt").write_text("", encoding="utf-8")
    (evidence / "provenance.json").write_text(
        json.dumps({"su2_config_origin": "https://github.com/su2code/SU2.git"}),
        encoding="utf-8-sig",
    )
    output = tmp_path / "audit.json"

    exit_code = main(["benchmark-audit", "--evidence-dir", str(evidence), "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 3
    assert payload["execution_passed"] is True
    assert payload["convergence_status"] == "not_converged"
    assert payload["validation_level"] == "L1"
    assert payload["engineering_validation"] is False
    assert payload["final_cl"] == -0.000002
    assert payload["final_cd"] == 0.007106
def test_main_prints_environment_diagnostics(capsys):
    assert main() == 0

    output = capsys.readouterr().out
    for label in ("Python:", "Gmsh:", "SU2:", "PyVista:", "CPU:", "RAM:"):
        assert label in output


def test_run_case_maps_explicit_inputs_and_writes_json_summary(tmp_path, capsys):
    source = tmp_path / "air.step"
    source.write_text("fixture", encoding="utf-8")
    su2 = tmp_path / "SU2_CFD.exe"
    su2.write_bytes(b"fixture")
    summary = tmp_path / "summary.json"
    observed = {}

    class FakePipeline:
        def __init__(self, **kwargs):
            observed["init"] = kwargs

        def run(self, source_step, parameters, case_root):
            observed.update(source=source_step, parameters=parameters, case_root=case_root)
            report = case_root / "report.html"
            history = case_root / "history.csv"
            flow = case_root / "flow.vtu"
            for path in (report, history, flow):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("evidence", encoding="utf-8")
            return SimpleNamespace(
                case_root=case_root,
                fingerprint="a" * 64,
                manifest_path=case_root / "case_manifest.json",
                executed_steps=("stage", "report"),
                reused_steps=(),
                context={
                    "report_path": report,
                    "history_path": history,
                    "flow_vtu": flow,
                    "convergence": SimpleNamespace(
                        status=SimpleNamespace(value="unconverged"),
                        reason_code="CFD_NOT_CONVERGED",
                        final_cl=0.5,
                        final_cd=0.05,
                    ),
                },
            )

    exit_code = run_case(
        [
            "--step", str(source), "--output", str(tmp_path / "case"),
            "--su2", str(su2), "--velocity", "15", "--angle", "6",
            "--s-ref", "1.2", "--c-ref", "0.4", "--mass", "3.5",
            "--target-size", "0.5", "--iterations", "10",
            "--summary-json", str(summary),
        ],
        pipeline_factory=FakePipeline,
    )

    assert exit_code == 0
    assert observed["source"] == source.resolve()
    assert observed["parameters"].mesh.mode is MeshMode.PREVIEW
    assert observed["parameters"].flow.angle_of_attack_deg == 6.0
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["workflow_status"] == "completed"
    assert payload["execution_status"] == "completed"
    assert payload["convergence_status"] == "unconverged"
    assert payload["credibility"] == "invalid"
    assert payload["coefficients_usable"] is False
    assert payload["history_csv"] == str((tmp_path / "case" / "history.csv").resolve())
    assert json.loads(capsys.readouterr().out)["reason_code"] == "CFD_NOT_CONVERGED"


def test_run_case_writes_stable_error_evidence(tmp_path, capsys):
    summary = tmp_path / "summary.json"
    exit_code = run_case(
        [
            "--step", str(tmp_path / "missing.step"),
            "--output", str(tmp_path / "case"),
            "--su2", str(tmp_path / "missing.exe"),
            "--summary-json", str(summary),
        ]
    )

    assert exit_code == 2
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["workflow_status"] == "failed"
    assert payload["execution_status"] == "failed"
    assert payload["error_code"] == "HEADLESS_INPUT_NOT_FOUND"
    assert json.loads(capsys.readouterr().out) == payload
