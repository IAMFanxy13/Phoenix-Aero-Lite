import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from phoenix_aero_lite.geometry.wing_reference import WingReferenceResult
from phoenix_aero_lite.solver.convergence import ConvergenceStatus
from phoenix_aero_lite.web.app import create_app
from phoenix_aero_lite.web.jobs import LocalJobService
from phoenix_aero_lite.web.grid_studies import LocalGridStudyService
from phoenix_aero_lite.utilities.first_run_check import (
    FirstRunCheck,
    FirstRunReport,
)
from phoenix_aero_lite.web.model_service import LocalModelService
from tests.unit.web.test_model_service import fake_preview, fake_scene
from tests.unit.web.test_jobs import (
    pressure_scene,
    streamline_scene,
    velocity_scene,
    write_result_manifest,
    y_plus_scene,
)


def fake_result(case_root: Path):
    artifacts = {}
    for name in ("history.csv", "flow.vtu", "surface_flow.vtu", "report.html"):
        path = case_root / name
        path.write_text(f"artifact {name}", encoding="utf-8")
        artifacts[name] = path
    write_result_manifest(case_root, artifacts.values())
    return SimpleNamespace(
        case_root=case_root,
        fingerprint="a" * 64,
        reused_steps=(),
        executed_steps=("stage", "inspect", "mesh", "config", "solve", "parse", "visualize", "report"),
        stage_sources={},
        manifest_path=case_root / "case_manifest.json",
        context={
            "convergence": SimpleNamespace(
                status=ConvergenceStatus.STAGNATED,
                reason_code="RESIDUAL_STAGNATION",
                final_cl=0.5,
                final_cd=0.06,
            ),
            "mesh_quality": {
                "negative_quality_count": 0,
                "non_manifold_face_count": 0,
                "near_wall": {"drag_fidelity": "preview_only"},
            },
            "history_path": artifacts["history.csv"],
            "flow_vtu": artifacts["flow.vtu"],
            "surface_flow_vtu": artifacts["surface_flow.vtu"],
            "report_path": artifacts["report.html"],
        },
    )


def client(tmp_path):
    service = LocalJobService(
        tmp_path / "jobs",
        runner=lambda _source, _parameters, case_root, _token: fake_result(case_root),
        pressure_scene_builder=pressure_scene,
        y_plus_scene_builder=y_plus_scene,
        velocity_scene_builder=velocity_scene,
        streamline_scene_builder=streamline_scene,
    )
    models = LocalModelService(
        tmp_path / "models", preview_builder=fake_preview, scene_builder=fake_scene
    )
    return TestClient(
        create_app(tmp_path, job_service=service, model_service=models)
    ), service


def form():
    return {
        "velocity_m_s": "15",
        "angle_of_attack_deg": "6",
        "s_ref_m2": "1",
        "c_ref_m": "0.4",
        "mass_kg": "2",
        "density_kg_m3": "1.225",
        "dynamic_viscosity_pa_s": "0.000017894",
        "analysis_mode": "fast",
        "target_cell_size_m": "0.5",
        "max_iterations": "100",
    }


def wait_job(http, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        payload = http.get(f"/api/jobs/{job_id}").json()
        if payload["state"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def wait_grid_study(http, study_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        payload = http.get(f"/api/grid-studies/{study_id}").json()
        if payload["state"] in {"completed", "blocked", "failed", "cancelled"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("grid study did not finish")


def test_health_is_local_and_reports_tool_state(tmp_path):
    http, service = client(tmp_path)
    with http:
        response = http.get("/api/health")

    assert response.status_code == 200
    assert response.json()["service"] == "Phoenix Aero Lite"
    assert response.json()["bind_policy"] == "loopback_only"
    service.shutdown()


def test_upload_inspect_and_open_only_registered_model_preview(tmp_path):
    http, service = client(tmp_path)
    with http:
        uploaded = http.post(
            "/api/models",
            files={"model": ("飞机.step", b"STEP DATA", "application/octet-stream")},
        )
        assert uploaded.status_code == 201
        payload = uploaded.json()
        fetched = http.get(f"/api/models/{payload['model_id']}")
        override = http.patch(
            f"/api/models/{payload['model_id']}/parameters/s_ref_m2",
            json={"value": 0.91},
        )
        batch = http.put(
            f"/api/models/{payload['model_id']}/parameters",
            json={
                "values": {
                    "nose_axis": "+Z",
                    "up_axis": "+Y",
                    "span_axis": "+X",
                    "c_ref_m": 0.41,
                }
            },
        )
        restored_parameter = http.post(
            f"/api/models/{payload['model_id']}/parameters/s_ref_m2/restore"
        )
        preview = http.get(payload["artifacts"]["preview.html"])
        traversal = http.get(
            f"/api/models/{payload['model_id']}/artifacts/..%2Fmodel.json"
        )

    assert payload["state"] == "ready"
    assert payload["inspection"]["dimensions_m"] == [2.0, 0.4, 1.2]
    assert fetched.json() == payload
    assert override.status_code == 200
    assert override.json()["parameters"]["s_ref_m2"]["detected_value"] == "unresolved"
    assert restored_parameter.status_code == 200
    assert restored_parameter.json()["parameters"]["s_ref_m2"]["current_value"] == "unresolved"
    assert override.json()["parameters"]["s_ref_m2"]["current_value"] == 0.91
    assert batch.status_code == 200
    assert batch.json()["parameters"]["c_ref_m"]["current_value"] == 0.41
    assert batch.json()["parameters"]["nose_axis"]["current_value"] == "+Z"
    assert preview.status_code == 200
    assert b"real scene" in preview.content
    assert traversal.status_code in {404, 422}
    service.shutdown()


def test_selected_real_surface_tags_are_validated_and_recompute_reference(tmp_path):
    job_service = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)
    models = LocalModelService(
        tmp_path / "models",
        preview_builder=fake_preview,
        scene_builder=fake_scene,
        wing_reference_calculator=lambda _mesh, tags, **_axes: WingReferenceResult(
            tags, 0.8, 0.4, 2.0, 0.8, 0.79, "medium", "真实曲面投影"
        ),
    )
    app = create_app(tmp_path, job_service=job_service, model_service=models)
    with TestClient(app) as http:
        model = http.post(
            "/api/models", files={"model": ("air.step", b"STEP DATA")}
        ).json()
        selected = http.put(
            f"/api/models/{model['model_id']}/wing-surfaces",
            json={"surface_tags": [20, 10]},
        )
        invalid = http.put(
            f"/api/models/{model['model_id']}/wing-surfaces",
            json={"surface_tags": [999]},
        )

    assert selected.status_code == 200
    payload = selected.json()
    assert payload["selected_surface_tags"] == [10, 20]
    assert payload["parameters"]["s_ref_m2"]["current_value"] == 0.8
    assert payload["parameters"]["c_ref_m"]["current_value"] == 0.4
    assert payload["parameters"]["span_m"]["current_value"] == 2.0
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "WING_SURFACE_TAG_INVALID"
    job_service.shutdown()


def test_submit_poll_and_download_only_registered_artifact(tmp_path):
    http, service = client(tmp_path)
    with http:
        response = http.post(
            "/api/jobs",
            data=form(),
            files={"model": ("飞机.step", b"STEP DATA", "application/octet-stream")},
        )
        assert response.status_code == 202
        assert response.json()["request"]["mesh_mode"] == "preview"
        job_id = response.json()["job_id"]
        final = wait_job(http, job_id)
        artifact = http.get(f"/api/jobs/{job_id}/artifacts/history.csv")
        surface = http.get(f"/api/jobs/{job_id}/artifacts/surface_flow.vtu")
        generated = http.post(f"/api/jobs/{job_id}/scenes/pressure?field=cp")
        pressure_scene_response = http.get(
            generated.json()["artifacts"]["pressure_cp.html"]
        )
        y_plus = http.post(f"/api/jobs/{job_id}/scenes/y-plus")
        velocity = http.post(
            f"/api/jobs/{job_id}/scenes/velocity?preset=longitudinal"
        )
        streamlines = http.post(
            f"/api/jobs/{job_id}/scenes/streamlines?density=sparse"
        )
        traversal = http.get(f"/api/jobs/{job_id}/artifacts/..%2Fjob.json")

    assert final["state"] == "completed"
    assert final["credibility"] == "caution"
    assert final["coefficients_usable"] is False
    assert final["execution_status"] == "completed"
    assert final["scientific_use_level"] == "diagnostic_only"
    assert final["scientific_evidence"]["convergence_status"] == "stagnated"
    assert final["quantity_evidence"]["CL"]["usable_for_diagnostic"] is True
    assert final["quantity_evidence"]["CL"]["usable_for_engineering"] is False
    assert final["quantity_evidence"]["y_plus"]["evidence_status"] == "missing"
    assert final["user_diagnostics"][0]["code"] == "CONVERGENCE_STAGNATED"
    assert final["user_diagnostics"][0]["can_view_fields"] is True
    assert final["conservative_retry_available"] is True
    assert final["aerodynamic_summary"]["lift_n"] == 68.90625
    assert final["aerodynamic_summary"]["drag_n"] == pytest.approx(8.26875)
    assert final["aerodynamic_summary"]["weight_n"] == 19.6133
    assert final["aerodynamic_summary"]["lift_weight_ratio"] > 3.5
    assert "不等于" in final["aerodynamic_summary"]["takeoff_boundary_zh"]
    assert artifact.status_code == 200
    assert artifact.content == b"artifact history.csv"
    assert surface.status_code == 200
    assert surface.content == b"artifact surface_flow.vtu"
    assert generated.status_code == 201
    assert pressure_scene_response.status_code == 200
    assert b"cp" in pressure_scene_response.content
    assert y_plus.status_code == 409
    assert y_plus.json()["detail"]["code"] == "Y_PLUS_EVIDENCE_UNAVAILABLE"
    assert velocity.status_code == 201
    assert "velocity_longitudinal.html" in velocity.json()["artifacts"]
    assert streamlines.status_code == 201
    assert "streamlines_sparse.html" in streamlines.json()["artifacts"]
    assert traversal.status_code in {404, 422}
    service.shutdown()


def test_conservative_retry_api_creates_audited_child_and_only_once(tmp_path):
    http, service = client(tmp_path)
    with http:
        original = http.post(
            "/api/jobs",
            data=form(),
            files={"model": ("air.step", b"STEP DATA")},
        ).json()
        final = wait_job(http, original["job_id"])
        retried = http.post(
            f"/api/jobs/{final['job_id']}/retry-conservative"
        )
        repeated = http.post(
            f"/api/jobs/{final['job_id']}/retry-conservative"
        )

    assert retried.status_code == 202
    child = retried.json()
    assert child["job_id"] != final["job_id"]
    assert child["parent_job_id"] == final["job_id"]
    assert child["retry_attempt"] == 1
    assert child["automatic_changes"]["max_iterations"]["old"] == 100
    assert repeated.status_code == 400
    assert repeated.json()["detail"]["code"] == "JOB_CONSERVATIVE_RETRY_ALREADY_USED"
    service.shutdown()


def test_rejects_non_step_and_invalid_flow_inputs(tmp_path):
    http, service = client(tmp_path)
    with http:
        wrong_type = http.post(
            "/api/jobs", data=form(), files={"model": ("air.txt", b"bad")}
        )
        invalid = form()
        invalid["velocity_m_s"] = "0"
        wrong_value = http.post(
            "/api/jobs", data=invalid, files={"model": ("air.step", b"STEP")}
        )

    assert wrong_type.status_code == 400
    assert wrong_type.json()["detail"]["code"] == "MODEL_MUST_BE_STEP"
    assert wrong_value.status_code == 400
    assert "FLOW_VELOCITY" in wrong_value.json()["detail"]["code"]
    service.shutdown()


def test_unknown_job_and_cancel_are_stable(tmp_path):
    http, service = client(tmp_path)
    with http:
        missing = http.get("/api/jobs/not-found")
        cancel_missing = http.post("/api/jobs/not-found/cancel")

    assert missing.status_code == 404
    assert cancel_missing.status_code == 404
    service.shutdown()


def test_preflight_api_returns_actionable_public_checks_without_local_paths(tmp_path):
    service = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)
    report = FirstRunReport(
        (
            FirstRunCheck(
                "SU2_RUNTIME",
                "SU2",
                "blocker",
                "SU2 不可用。",
                "按官方安装说明配置 SU2。",
            ),
        )
    )
    app = create_app(
        tmp_path,
        job_service=service,
        preflight_provider=lambda: report,
    )

    with TestClient(app) as http:
        response = http.get("/api/preflight")

    assert response.status_code == 200
    assert response.json() == {
        "ready": False,
        "checks": [
            {
                "code": "SU2_RUNTIME",
                "label_zh": "SU2",
                "status": "blocker",
                "summary_zh": "SU2 不可用。",
                "remediation_zh": "按官方安装说明配置 SU2。",
            }
        ],
    }
    assert str(tmp_path) not in response.text
    service.shutdown()


def test_analysis_preset_api_is_backend_owned_and_explains_evidence_limit(tmp_path):
    http, service = client(tmp_path)
    with http:
        response = http.get("/api/presets")

    assert response.status_code == 200
    payload = response.json()
    assert [item["code"] for item in payload] == [
        "geometry_check",
        "trend",
        "standard",
        "grid_study",
        "custom",
    ]
    standard = next(item for item in payload if item["code"] == "standard")
    assert standard["target_y_plus"] == 1.0
    assert standard["boundary_layer"] == "enabled_and_audited"
    assert standard["evidence_ceiling"] == "engineering_if_all_gates_pass"
    service.shutdown()


def test_grid_study_api_submits_and_exposes_three_child_jobs(tmp_path):
    counts = {0.75: 8000, 0.5: 64000, 0.33: 512000}

    def runner(_source, parameters, case_root, _token):
        result = fake_result(case_root)
        target = round(parameters.mesh.target_cell_size_m, 2)
        result.context["convergence"].status = ConvergenceStatus.CONVERGED
        result.context["mesh_quality"].update(
            node_count=counts[target] // 2,
            cell_count=counts[target],
        )
        result.context["convergence"].final_cl = {
            0.75: 0.5,
            0.5: 0.55,
            0.33: 0.56,
        }[target]
        result.context["convergence"].final_cd = {
            0.75: 0.05,
            0.5: 0.045,
            0.33: 0.043,
        }[target]
        return result

    jobs = LocalJobService(tmp_path / "jobs", runner=runner)
    studies = LocalGridStudyService(tmp_path / "studies", job_service=jobs)
    app = create_app(
        tmp_path,
        job_service=jobs,
        grid_study_service=studies,
    )
    payload = form()
    payload["analysis_mode"] = "grid_study"
    with TestClient(app) as http:
        submitted = http.post(
            "/api/grid-studies",
            data=payload,
            files={"model": ("air.step", b"STEP DATA")},
        )
        assert submitted.status_code == 202
        final = wait_grid_study(http, submitted.json()["study_id"])
        listed = http.get("/api/grid-studies")

    assert final["state"] == "completed"
    assert final["analysis_status"] == "computed"
    assert list(final["levels"]) == ["coarse", "medium", "fine"]
    assert all(item["parent_job_id"] == final["study_id"] for item in final["levels"].values())
    assert all(item["gci_computable"] for item in final["quantities"].values())
    assert listed.status_code == 200
    assert listed.json()[0]["study_id"] == final["study_id"]
    jobs.shutdown()


def test_browser_security_headers_keep_service_same_origin_and_api_private(tmp_path):
    http, service = client(tmp_path)
    with http:
        page = http.get("/")
        api = http.get("/api/health")
        cross_origin = http.options(
            "/api/health",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    for response in (page, api):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
        assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert api.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in cross_origin.headers
    service.shutdown()
