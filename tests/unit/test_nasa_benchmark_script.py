from pathlib import Path

from scripts.run_nasa_naca0012_sst_benchmark import (
    prepare_continuation_config,
    stage_restart,
)


def test_prepare_continuation_changes_only_audited_runtime_controls():
    source = "RESTART_SOL= NO\nITER= 2500\nSCREEN_OUTPUT= (INNER_ITER, RMS_PRESSURE, LIFT, DRAG)\n"

    configured, changes = prepare_continuation_config(source, iterations=2500)

    assert "RESTART_SOL= YES" in configured
    assert "ITER= 2500" in configured
    assert "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)" in configured
    assert changes == {
        "RESTART_SOL": {"from": "NO", "to": "YES"},
        "ITER": {"from": "2500", "to": "2500"},
        "HISTORY_OUTPUT": {"from": None, "to": "(ITER, RMS_RES, AERO_COEFF)"},
    }


def test_stage_restart_uses_su2_solution_filename_without_changing_bytes(tmp_path: Path):
    source = tmp_path / "restart_flow.dat"
    source.write_bytes(b"official restart bytes")

    staged = stage_restart(source, tmp_path / "run")

    assert staged.name == "solution_flow.dat"
    assert staged.read_bytes() == source.read_bytes()
