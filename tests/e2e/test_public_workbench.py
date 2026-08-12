from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
from threading import Thread
import time
from types import SimpleNamespace

import gmsh
import numpy as np
from playwright.sync_api import expect, sync_playwright
import pytest
import pyvista as pv
import uvicorn

from phoenix_aero_lite.geometry.gmsh_geometry import GmshGeometryAdapter
from phoenix_aero_lite.utilities.first_run_check import FirstRunCheck, FirstRunReport
from phoenix_aero_lite.web.app import create_app
from phoenix_aero_lite.web.jobs import LocalJobService
from phoenix_aero_lite.solver.convergence import ConvergenceStatus


pytestmark = pytest.mark.e2e


def _public_synthetic_aircraft(path: Path) -> Path:
    """Create a public synthetic STEP through the official Gmsh OCC API."""

    def extrude_xy(points: tuple[tuple[float, float], ...], z: float, height: float):
        point_tags = [gmsh.model.occ.addPoint(x, y, z) for x, y in points]
        line_tags = [
            gmsh.model.occ.addLine(point_tags[index], point_tags[(index + 1) % len(points)])
            for index in range(len(points))
        ]
        wire = gmsh.model.occ.addCurveLoop(line_tags)
        face = gmsh.model.occ.addPlaneSurface([wire])
        gmsh.model.occ.extrude([(2, face)], 0, 0, height)

    def extrude_xz(points: tuple[tuple[float, float], ...], y: float, width: float):
        point_tags = [gmsh.model.occ.addPoint(x, y, z) for x, z in points]
        line_tags = [
            gmsh.model.occ.addLine(point_tags[index], point_tags[(index + 1) % len(points)])
            for index in range(len(points))
        ]
        wire = gmsh.model.occ.addCurveLoop(line_tags)
        face = gmsh.model.occ.addPlaneSurface([wire])
        gmsh.model.occ.extrude([(2, face)], 0, width, 0)

    gmsh.initialize()
    previous_target_unit = gmsh.option.getString("Geometry.OCCTargetUnit")
    try:
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.add("public_fixed_wing_uav")
        # STEP commonly carries CAD coordinates in millimetres.  These values
        # produce a 2.4 m long, 2.9 m span public UAV after the adapter's unit
        # normalization, matching the same official OCC path as user models.
        gmsh.model.occ.addCone(-1150, 0, 0, 250, 0, 0, 35, 130)
        gmsh.model.occ.addCylinder(-900, 0, 0, 1800, 0, 0, 130)
        gmsh.model.occ.addCone(900, 0, 0, 350, 0, 0, 130, 12)

        extrude_xy(
            ((250, 80), (-300, 80), (-420, 1450), (-50, 1450)),
            -35,
            70,
        )
        extrude_xy(
            ((-300, -80), (250, -80), (-50, -1450), (-420, -1450)),
            -35,
            70,
        )
        extrude_xy(
            ((-620, 70), (-1000, 70), (-1080, 600), (-760, 600)),
            -22,
            44,
        )
        extrude_xy(
            ((-1000, -70), (-620, -70), (-760, -600), (-1080, -600)),
            -22,
            44,
        )
        extrude_xz(
            ((-700, 65), (-1080, 65), (-1050, 340), (-880, 550)),
            -28,
            56,
        )
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.option.setString("Geometry.OCCTargetUnit", previous_target_unit)
        gmsh.finalize()
    assert path.is_file() and path.stat().st_size > 0
    return path


def test_public_synthetic_aircraft_has_uav_proportions(tmp_path: Path):
    model = _public_synthetic_aircraft(tmp_path / "public-uav.step")

    inspection = GmshGeometryAdapter().inspect_step(model)

    length, span, height = inspection.dimensions_m
    assert inspection.volume_count >= 6
    assert inspection.surface_count > 25
    assert length > 2.0
    assert span > 2.6
    assert height > 0.45


def _ready_report() -> FirstRunReport:
    return FirstRunReport(
        (
            FirstRunCheck(
                "E2E_RUNTIME",
                "端到端测试环境",
                "pass",
                "公开合成模型测试环境可用。",
                "无需操作。",
            ),
        )
    )


def _public_grid_result(case_root: Path, target_cell_size_m: float):
    target = round(target_cell_size_m, 2)
    values = {
        0.75: (4000, 8000, 0.50, 0.050),
        0.50: (32000, 64000, 0.55, 0.045),
        0.33: (256000, 512000, 0.56, 0.043),
    }[target]
    (case_root / "history.csv").write_text(
        '"Inner_Iter","CL","CD"\n0,0.50,0.05\n1,0.56,0.043\n',
        encoding="utf-8",
    )
    (case_root / "report.html").write_text(
        "<html><body><h1>Public synthetic E2E report</h1></body></html>",
        encoding="utf-8",
    )
    volume = pv.ImageData(dimensions=(10, 9, 8), spacing=(0.2, 0.2, 0.2))
    flow = volume.cast_to_unstructured_grid()
    flow.point_data["Velocity"] = np.tile((15.0, 0.0, 0.0), (flow.n_points, 1))
    flow.save(case_root / "flow.vtu")
    surface = pv.Cube(center=(0.9, 0.8, 0.7), x_length=0.4, y_length=0.5, z_length=0.3).triangulate()
    surface.point_data["Pressure_Coefficient"] = np.linspace(-0.8, 0.6, surface.n_points)
    surface.point_data["Pressure"] = np.linspace(100_900.0, 101_400.0, surface.n_points)
    surface.point_data["Y_Plus"] = np.linspace(0.2, 3.7, surface.n_points)
    surface.cast_to_unstructured_grid().save(case_root / "surface_flow.vtu")
    stdout = case_root / "stdout.txt"
    stderr = case_root / "stderr.txt"
    stdout.write_text("SU2 public synthetic E2E output", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    artifacts = [
        case_root / "history.csv",
        case_root / "flow.vtu",
        case_root / "surface_flow.vtu",
        case_root / "report.html",
        stdout,
        stderr,
    ]
    records = []
    for path in artifacts:
        content = path.read_bytes()
        records.append(
            {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(content).hexdigest().upper(),
                "size": len(content),
            }
        )
    (case_root / "case_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "fingerprint": "a" * 64,
                "provenance": {},
                "steps": {
                    "result": {
                        "status": "complete",
                        "artifacts": records,
                        "metadata": {},
                        "input_fingerprint": "b" * 64,
                        "producer_id": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(
        case_root=case_root,
        manifest_path=case_root / "case_manifest.json",
        fingerprint="a" * 64,
        reused_steps=(),
        executed_steps=(
            "stage",
            "inspect",
            "mesh",
            "config",
            "solve",
            "parse",
            "visualize",
            "report",
        ),
        stage_sources={},
        context={
            "convergence": SimpleNamespace(
                status=ConvergenceStatus.CONVERGED,
                reason_code="TARGET_AND_FORCE_PLATEAU",
                final_cl=values[2],
                final_cd=values[3],
            ),
            "mesh_quality": {
                "node_count": values[0],
                "cell_count": values[1],
                "negative_quality_count": 0,
                "non_manifold_face_count": 0,
                "near_wall": {
                    "required": True,
                    "present": True,
                    "drag_fidelity": "validated_near_wall_layers",
                    "y_plus": {
                        "status": "computed",
                        "value": 1.1,
                        "source": "public synthetic solved wall field",
                    },
                },
            },
            "history_path": case_root / "history.csv",
            "flow_vtu": case_root / "flow.vtu",
            "surface_flow_vtu": case_root / "surface_flow.vtu",
            "report_path": case_root / "report.html",
            "process_result": SimpleNamespace(
                stdout_path=stdout,
                stderr_path=stderr,
            ),
        }
    )


@contextmanager
def _serve_public_app(root: Path, *, runner=None):
    jobs = LocalJobService(
        root / "jobs",
        runner=runner
        or (
            lambda _source, parameters, case_root, _token: _public_grid_result(
                case_root, parameters.mesh.target_cell_size_m
            )
        ),
    )
    app = create_app(root, job_service=jobs, preflight_provider=_ready_report)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
    )
    thread = Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="pal-e2e-server",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        jobs.shutdown()
        raise RuntimeError("E2E_SERVER_START_FAILED")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        listener.close()
        jobs.shutdown()


def test_public_step_upload_renders_real_picker_and_toggles_surface(tmp_path: Path):
    model = _public_synthetic_aircraft(tmp_path / "public-aircraft.step")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            browser_errors: list[str] = []
            page.on(
                "console",
                lambda message: (
                    browser_errors.append(f"console: {message.text}")
                    if message.type == "error"
                    else None
                ),
            )
            page.on("pageerror", lambda error: browser_errors.append(f"page: {error}"))
            page.on(
                "requestfailed",
                lambda request: browser_errors.append(
                    f"request: {request.method} {request.url} {request.failure}"
                ),
            )
            with _serve_public_app(tmp_path / "runtime") as base_url:
                page.goto(base_url, wait_until="networkidle")
                expect(page).to_have_title("Phoenix Aero Lite")
                expect(page.locator("#preflight-status")).to_contain_text("环境自检通过")
                expect(page.locator('[data-step="model"]')).to_contain_text("🛩️")
                expect(page.locator('[data-step="confirm"]')).to_contain_text("🧭")
                expect(page.locator('[data-step="run"]')).to_contain_text("⚙️")

                page.locator("#model").set_input_files(model)
                expect(page.locator("#model-summary")).to_be_visible(timeout=120_000)
                expect(page.locator("#model-topology")).to_contain_text("实体")
                expect(page.locator("#model-viewer")).to_be_visible()

                frame = page.frame_locator("#model-viewer")
                expect(frame.locator("#phoenix-surface-picker")).to_have_count(
                    1, timeout=60_000
                )
                canvas = frame.locator("canvas").first
                expect(canvas).to_be_visible(timeout=60_000)
                canvas.click(position={"x": 300, "y": 250})
                expect(page.locator("#wing-selection-count")).not_to_contain_text(
                    "已选择 0 个曲面", timeout=30_000
                )

                page.locator("#confirm-model").click()
                expect(page.locator("#submit-button")).to_be_enabled(timeout=30_000)
                # Opening a native <details> element is not the behavior under
                # test here.  A synthetic pointer click can stall while the
                # independent VTK iframe is serializing a large scene, so set
                # the standard DOM property and keep real clicks for picking,
                # submission and result controls below.
                page.locator("#advanced-settings").evaluate(
                    "element => { element.open = true; }"
                )
                page.locator("#analysis-mode").select_option("grid_study")
                expect(page.locator("#submit-button")).to_contain_text("📊 三档分析")
                invalid = page.locator("#job-form :invalid").evaluate_all(
                    "elements => elements.map(element => ({id: element.id, name: element.name, value: element.value, message: element.validationMessage}))"
                )
                assert invalid == []
                page.locator("#submit-button").click()
                page.wait_for_timeout(2_000)
                assert page.locator("#form-error").text_content() == ""
                assert browser_errors == []
                expect(page.locator("#grid-study-view")).to_be_visible(timeout=30_000)
                expect(page.locator("#state-chip")).to_contain_text(
                    "✅ 完成", timeout=30_000
                )
                expect(page.locator("#state-chip")).to_have_class(
                    "chip state-completed"
                )
                expect(page.locator("#grid-study-levels tr")).to_have_count(3)
                expect(page.locator("#grid-study-gci")).to_contain_text("GCI")

                artifact_root = Path(
                    os.environ.get("PAL_E2E_ARTIFACT_DIR", tmp_path / "artifacts")
                )
                artifact_root.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=artifact_root / "public_workbench_surface_selected.png",
                    full_page=True,
                )
                (artifact_root / "browser_errors.json").write_text(
                    json.dumps(browser_errors, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                canvas.click(position={"x": 300, "y": 250})
                expect(page.locator("#wing-selection-count")).to_contain_text(
                    "已选择 0 个曲面", timeout=30_000
                )

                expect(page.locator("#history-body tr")).to_have_count(4)
                assert "study=" in page.url
                page.reload(wait_until="networkidle")
                expect(page.locator("#grid-study-view")).to_be_visible(timeout=30_000)
                expect(page.locator("#state-chip")).to_contain_text("✅ 完成")
                expect(page.locator("#grid-study-levels tr")).to_have_count(3)
                (artifact_root / "browser_errors.json").write_text(
                    json.dumps(browser_errors, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                assert browser_errors == []

                page.locator("#history-body tr").nth(1).click()
                expect(page.locator("#state-chip")).to_contain_text("✅ 完成")
                assert "job=" in page.url
                expect(page.locator('[data-view="pressure"]')).to_be_enabled()
                expect(page.locator('[data-view="yplus"]')).to_be_enabled()
                expect(page.locator('[data-view="velocity"]')).to_be_enabled()
                expect(page.locator('[data-view="streamlines"]')).to_be_enabled()

                page.locator('[data-view="pressure"]').click()
                expect(page.locator("#pressure-controls")).to_be_visible()
                expect(page.locator("#scene-title")).to_contain_text("Cp", timeout=60_000)
                expect(page.frame_locator("#model-viewer").locator("#phoenix-scene-controls")).to_have_count(1, timeout=60_000)

                page.locator("#pressure-field").select_option("pressure")
                expect(page.locator("#scene-title")).to_contain_text("Pa", timeout=60_000)
                page.locator('[data-view="yplus"]').click()
                expect(page.locator("#scene-title")).to_contain_text("Y+", timeout=60_000)
                expect(page.locator("#scalar-probe")).to_contain_text("无量纲")
                expect(page.locator("#scalar-min")).to_have_value("0.200000")
                page.locator("#scalar-min").fill("0.5")
                page.locator("#scalar-max").fill("2.5")
                page.locator("#apply-scalar-range").click()
                expect(page.locator("#scene-title")).to_contain_text("Y+", timeout=60_000)
                expect(page.locator("#scalar-min")).to_have_value("0.5")
                expect(page.locator("#scalar-max")).to_have_value("2.5")
                page.locator('[data-view="pressure"]').click()
                expect(page.locator("#scene-title")).to_contain_text("Pa", timeout=60_000)
                expect(page.locator("#scalar-min")).to_have_value("100900")
                page.locator('[data-view="yplus"]').click()
                expect(page.locator("#scalar-min")).to_have_value("0.5")
                page.locator("#reset-scalar-range").click()
                expect(page.locator("#scene-title")).to_contain_text("Y+", timeout=60_000)
                expect(page.locator("#scalar-min")).to_have_value("0.200000")
                page.screenshot(
                    path=artifact_root / "public_workbench_y_plus.png",
                    full_page=True,
                )

                page.locator('[data-view="velocity"]').click()
                expect(page.locator("#velocity-controls")).to_be_visible()
                expect(page.locator("#scene-title")).to_contain_text("速度截面", timeout=60_000)
                page.locator('[data-view="streamlines"]').click()
                expect(page.locator("#streamline-controls")).to_be_visible()
                expect(page.locator("#scene-title")).to_contain_text("三维流线", timeout=60_000)
                expect(page.locator("#artifact-links a", has_text="报告")).to_have_count(1)

                page.reload(wait_until="networkidle")
                expect(page.locator("#state-chip")).to_contain_text("✅ 完成")
                expect(page.locator('[data-view="yplus"]')).to_be_enabled()
                (artifact_root / "browser_errors.json").write_text(
                    json.dumps(browser_errors, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                assert browser_errors == []
        finally:
            browser.close()


def test_public_browser_cancels_fails_and_restores_terminal_jobs(tmp_path: Path):
    model = _public_synthetic_aircraft(tmp_path / "public-cancel-aircraft.step")
    first_entered = threading.Event()
    calls = 0

    def cancellation_then_failure(_source, _parameters, _case_root, token):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            while not token.is_cancelled:
                time.sleep(0.01)
            raise RuntimeError("cancelled")
        raise RuntimeError("SOLVER_FAILED")

    runtime_root = tmp_path / "restartable-runtime"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            browser_errors: list[str] = []
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            with _serve_public_app(
                runtime_root, runner=cancellation_then_failure
            ) as base_url:
                page.goto(base_url, wait_until="networkidle")
                page.locator("#model").set_input_files(model)
                expect(page.locator("#model-summary")).to_be_visible(timeout=120_000)
                frame = page.frame_locator("#model-viewer")
                canvas = frame.locator("canvas").first
                expect(canvas).to_be_visible(timeout=60_000)
                canvas.click(position={"x": 300, "y": 250})
                expect(page.locator("#wing-selection-count")).not_to_contain_text(
                    "已选择 0 个曲面", timeout=30_000
                )
                page.locator("#confirm-model").click()
                expect(page.locator("#submit-button")).to_be_enabled(timeout=30_000)

                page.locator("#submit-button").click()
                assert first_entered.wait(5)
                expect(page.locator("#state-chip")).to_contain_text("⏳ 运行")
                page.locator("#cancel-button").click()
                expect(page.locator("#state-chip")).to_contain_text(
                    "🛑 取消", timeout=30_000
                )
                cancelled_id = page.url.split("job=", 1)[1]

                page.locator("#submit-button").click()
                expect(page.locator("#state-chip")).to_contain_text(
                    "⛔ 失败", timeout=30_000
                )
                expect(page.locator("#user-diagnostic")).to_be_visible()
                expect(page.locator("#diagnostic-happened")).to_contain_text("SU2")
                failed_id = page.url.split("job=", 1)[1]
                assert failed_id != cancelled_id
                assert browser_errors == []

            with _serve_public_app(
                runtime_root,
                runner=lambda *_args: (_ for _ in ()).throw(
                    RuntimeError("unexpected rerun")
                ),
            ) as restarted_url:
                page.goto(f"{restarted_url}/?job={failed_id}", wait_until="networkidle")
                expect(page.locator("#state-chip")).to_contain_text("⛔ 失败")
                expect(page.locator("#diagnostic-happened")).to_contain_text("SU2")
                expect(page.locator("#history-body tr")).to_have_count(2)
                assert browser_errors == []
        finally:
            browser.close()
