"""Official SU2 8.5.0 one-iteration smoke for the generated configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

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
from phoenix_aero_lite.solver.su2_config import render_su2_config


def test_official_su2_runs_one_iteration_on_synthetic_task5_mesh(
    tmp_path: Path,
    synthetic_step_factory,
    external_mesher,
    official_su2_validator_path: Path,
):
    """Run the exact injected executable, never PATH or an emulated parser."""

    step_path = synthetic_step_factory(tmp_path / "synthetic-wing.step")
    mesh_artifacts = external_mesher().build_external_mesh(
        step_path,
        MeshParameters(MeshMode.PREVIEW, 3.0),
        tmp_path / "task5-mesh",
    )
    case_directory = tmp_path / "su2-case"
    parameters = CaseParameters(
        flow=FlowParameters(30.0, 1.225, 1.7894e-5, 5.0),
        reference=ReferenceParameters(12.0, 2.0),
        aircraft=AircraftParameters(750.0),
        mesh=MeshParameters(MeshMode.PREVIEW, 3.0),
        solver=SolverParameters(1),
        output=OutputParameters(case_directory),
    )
    rendered = render_su2_config(
        parameters,
        mesh_artifacts.su2_path,
        mesh_artifacts.physical_groups,
        case_directory,
    )
    command = [
        str(official_su2_validator_path.resolve(strict=True)),
        "-t",
        "1",
        rendered.path.name,
    ]

    result = subprocess.run(
        command,
        cwd=case_directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    generated_files = sorted(
        path.name for path in case_directory.iterdir() if path.is_file()
    )
    generated_artifacts = {
        path.name: {
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in case_directory.iterdir()
        if path.is_file()
    }
    evidence = {
        "command": command,
        "cwd": str(case_directory),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "generated_files": generated_files,
        "generated_artifacts": generated_artifacts,
    }
    (tmp_path / "su2-smoke-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    combined = (result.stdout + "\n" + result.stderr).lower()
    forbidden = (
        "unknown option",
        "invalid option",
        "not found in the configuration file",
        "could not find marker",
        "mesh file format not recognized",
        "error loading shared library",
        "dll",
    )
    assert result.returncode == 0, json.dumps(evidence, ensure_ascii=False)
    assert not any(message in combined for message in forbidden), combined
    assert {
        "history.csv",
        "restart_flow.dat",
        "flow.vtu",
        "surface_flow.vtu",
    } <= set(generated_files)
    for name in (
        "history.csv",
        "restart_flow.dat",
        "flow.vtu",
        "surface_flow.vtu",
    ):
        assert generated_artifacts[name]["size_bytes"] > 0
        assert len(generated_artifacts[name]["sha256"]) == 64
    history_lines = (case_directory / "history.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) >= 2
    assert history_lines[0].strip()
    assert history_lines[1].strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
