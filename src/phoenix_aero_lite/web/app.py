"""FastAPI composition for the loopback-only Phoenix Aero Lite service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from importlib import metadata
import json
import math
from pathlib import Path
from typing import Annotated, Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from phoenix_aero_lite.app.pipeline import PhoenixCasePipeline
from phoenix_aero_lite.models.parameters import MeshMode
from phoenix_aero_lite.web.diagnostics import diagnostics_for_codes
from phoenix_aero_lite.web.jobs import JobSnapshot, LocalJobService
from phoenix_aero_lite.web.grid_studies import (
    GridStudySnapshot,
    LocalGridStudyService,
)
from phoenix_aero_lite.web.model_service import (
    LocalModelService,
    ModelSnapshot,
)
from phoenix_aero_lite.web.models import JobRequest, MAX_STEP_BYTES
from phoenix_aero_lite.web.presets import analysis_presets, resolve_solver_preset
from phoenix_aero_lite.utilities.first_run_check import (
    FirstRunReport,
    run_first_run_checks,
)
from phoenix_aero_lite.utilities.cache_policy import (
    acquire_cache_run_lease,
    enforce_cache_limit,
)


def create_app(
    project_root: Path,
    *,
    job_service: LocalJobService | None = None,
    grid_study_service: LocalGridStudyService | None = None,
    model_service: LocalModelService | None = None,
    preflight_provider: Callable[[], FirstRunReport] | None = None,
) -> FastAPI:
    """Create a local API without coupling routes to CFD implementation."""

    root = Path(project_root).resolve(strict=False)
    service = job_service or _production_job_service(root)
    studies = grid_study_service or LocalGridStudyService(
        root / "web-data" / "grid-studies", job_service=service
    )
    models = model_service or LocalModelService(root / "web-data" / "models")
    provide_preflight = preflight_provider or (
        lambda: run_first_run_checks(root, port=0)
    )

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if job_service is None:
            service.shutdown()

    app = FastAPI(
        title="Phoenix Aero Lite", version="0.1.0", lifespan=lifespan
    )
    app.state.job_service = service
    app.state.grid_study_service = studies
    app.state.model_service = models
    app.state.project_root = root
    app.state.owns_job_service = job_service is None
    package_root = Path(__file__).resolve().parents[1]
    templates = Jinja2Templates(directory=package_root / "templates" / "web")
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).resolve().parent / "static"),
        name="static",
    )

    @app.middleware("http")
    async def browser_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'self'; "
            "frame-src 'self'; connect-src 'self'; "
            "script-src 'self' 'unsafe-inline' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; worker-src 'self' blob:"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html.j2", {})

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "service": "Phoenix Aero Lite",
            "status": "ok",
            "bind_policy": "loopback_only",
            "job_root": str(service.root),
            "model_root": str(models.root),
        }

    @app.get("/api/preflight")
    def preflight() -> dict[str, object]:
        return provide_preflight().to_public_dict()

    @app.get("/api/presets")
    def presets() -> list[dict[str, object]]:
        return [item.to_dict() for item in analysis_presets().values()]

    @app.get("/api/models")
    def list_models() -> list[dict[str, object]]:
        return [_public_model(item) for item in models.list()]

    @app.get("/api/models/{model_id}")
    def get_model(model_id: str) -> dict[str, object]:
        return _public_model(_get_model_or_404(models, model_id))

    @app.post("/api/models", status_code=status.HTTP_201_CREATED)
    async def upload_model(
        model: Annotated[UploadFile, File()],
    ) -> dict[str, object]:
        filename = model.filename or "model.step"
        try:
            content = await model.read(MAX_STEP_BYTES + 1)
        finally:
            await model.close()
        try:
            snapshot = models.create(filename, content)
        except ValueError as error:
            raise _bad_request(str(error)) from None
        return _public_model(snapshot)

    @app.get("/api/models/{model_id}/artifacts/{artifact_name}")
    def get_model_artifact(model_id: str, artifact_name: str) -> FileResponse:
        snapshot = _get_model_or_404(models, model_id)
        selected = dict(snapshot.artifacts).get(artifact_name)
        if selected is None:
            raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND"})
        path = Path(selected).resolve(strict=False)
        if not path.is_relative_to(snapshot.model_directory) or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND"})
        if path.suffix.casefold() == ".html":
            return FileResponse(path, media_type="text/html")
        return FileResponse(path, filename=artifact_name)

    @app.patch("/api/models/{model_id}/parameters/{parameter_name}")
    def override_model_parameter(
        model_id: str,
        parameter_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        _get_model_or_404(models, model_id)
        if "value" not in payload:
            raise _bad_request("MODEL_PARAMETER_VALUE_MISSING")
        try:
            updated = models.override_parameter(
                model_id, parameter_name, payload["value"]
            )
        except ValueError as error:
            raise _bad_request(str(error)) from None
        return _public_model(updated)

    @app.put("/api/models/{model_id}/parameters")
    def override_model_parameters(
        model_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        _get_model_or_404(models, model_id)
        values = payload.get("values")
        if not isinstance(values, dict) or not values:
            raise _bad_request("MODEL_PARAMETER_VALUES_INVALID")
        try:
            updated = models.override_parameters(model_id, values)
        except ValueError as error:
            raise _bad_request(str(error)) from None
        return _public_model(updated)

    @app.post("/api/models/{model_id}/parameters/{parameter_name}/restore")
    def restore_model_parameter(
        model_id: str,
        parameter_name: str,
    ) -> dict[str, object]:
        _get_model_or_404(models, model_id)
        try:
            updated = models.restore_parameter(model_id, parameter_name)
        except ValueError as error:
            raise _bad_request(str(error)) from None
        return _public_model(updated)

    @app.put("/api/models/{model_id}/wing-surfaces")
    def select_wing_surfaces(
        model_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        _get_model_or_404(models, model_id)
        raw_tags = payload.get("surface_tags")
        if not isinstance(raw_tags, list) or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in raw_tags
        ):
            raise _bad_request("WING_SURFACE_SELECTION_INVALID")
        try:
            updated = models.select_wing_surfaces(model_id, tuple(raw_tags))
        except ValueError as error:
            raise _bad_request(str(error)) from None
        return _public_model(updated)

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, object]]:
        return [_public_snapshot(item) for item in service.list()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        return _public_snapshot(_get_or_404(service, job_id))

    @app.get("/api/grid-studies")
    def list_grid_studies() -> list[dict[str, object]]:
        return [_public_grid_study(item) for item in studies.list()]

    @app.get("/api/grid-studies/{study_id}")
    def get_grid_study(study_id: str) -> dict[str, object]:
        return _public_grid_study(_get_grid_study_or_404(studies, study_id))

    @app.post(
        "/api/grid-studies",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_grid_study(
        model: Annotated[UploadFile, File()],
        velocity_m_s: Annotated[float, Form()],
        angle_of_attack_deg: Annotated[float, Form()],
        s_ref_m2: Annotated[float, Form()],
        c_ref_m: Annotated[float, Form()],
        mass_kg: Annotated[float, Form()],
        density_kg_m3: Annotated[float, Form()] = 1.225,
        dynamic_viscosity_pa_s: Annotated[float, Form()] = 1.7894e-5,
        analysis_mode: Annotated[str, Form()] = "grid_study",
        target_cell_size_m: Annotated[float, Form()] = 0.5,
        max_iterations: Annotated[int, Form()] = 800,
    ) -> dict[str, object]:
        if analysis_mode.strip().casefold() != "grid_study":
            raise _bad_request("GRID_STUDY_MODE_REQUIRED")
        filename = model.filename or "model.step"
        try:
            content = await model.read(MAX_STEP_BYTES + 1)
        finally:
            await model.close()
        request = JobRequest(
            velocity_m_s=velocity_m_s,
            angle_of_attack_deg=angle_of_attack_deg,
            s_ref_m2=s_ref_m2,
            c_ref_m=c_ref_m,
            mass_kg=mass_kg,
            density_kg_m3=density_kg_m3,
            dynamic_viscosity_pa_s=dynamic_viscosity_pa_s,
            mesh_mode=MeshMode.STANDARD,
            target_cell_size_m=target_cell_size_m,
            max_iterations=max(800, max_iterations),
        )
        try:
            return _public_grid_study(studies.submit(filename, content, request))
        except ValueError as error:
            raise _bad_request(str(error)) from None

    @app.post("/api/grid-studies/{study_id}/cancel")
    def cancel_grid_study(study_id: str) -> dict[str, object]:
        _get_grid_study_or_404(studies, study_id)
        return {
            "study_id": study_id,
            "cancellation_requested": studies.cancel(study_id),
        }

    @app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
    async def submit_job(
        model: Annotated[UploadFile, File()],
        velocity_m_s: Annotated[float, Form()],
        angle_of_attack_deg: Annotated[float, Form()],
        s_ref_m2: Annotated[float, Form()],
        c_ref_m: Annotated[float, Form()],
        mass_kg: Annotated[float, Form()],
        density_kg_m3: Annotated[float, Form()] = 1.225,
        dynamic_viscosity_pa_s: Annotated[float, Form()] = 1.7894e-5,
        analysis_mode: Annotated[str, Form()] = "trend",
        target_cell_size_m: Annotated[float, Form()] = 0.5,
        max_iterations: Annotated[int, Form()] = 500,
    ) -> dict[str, object]:
        filename = model.filename or "model.step"
        try:
            content = await model.read(MAX_STEP_BYTES + 1)
        finally:
            await model.close()
        try:
            mode, preset_iterations = resolve_solver_preset(
                analysis_mode,
                requested_iterations=max_iterations,
            )
        except ValueError as error:
            raise _bad_request(str(error)) from None
        request = JobRequest(
            velocity_m_s=velocity_m_s,
            angle_of_attack_deg=angle_of_attack_deg,
            s_ref_m2=s_ref_m2,
            c_ref_m=c_ref_m,
            mass_kg=mass_kg,
            density_kg_m3=density_kg_m3,
            dynamic_viscosity_pa_s=dynamic_viscosity_pa_s,
            mesh_mode=mode,
            target_cell_size_m=target_cell_size_m,
            max_iterations=preset_iterations,
        )
        try:
            request.to_case_parameters(root / "web-data" / "validation")
            snapshot = service.submit(filename, content, request)
        except ValueError as error:
            raise _bad_request(str(error)) from None
        return _public_snapshot(snapshot)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, object]:
        _get_or_404(service, job_id)
        return {"job_id": job_id, "cancellation_requested": service.cancel(job_id)}

    @app.post(
        "/api/jobs/{job_id}/retry-conservative",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_job_conservatively(job_id: str) -> dict[str, object]:
        _get_or_404(service, job_id)
        try:
            return _public_snapshot(service.retry_conservative(job_id))
        except ValueError as error:
            raise _bad_request(str(error)) from None

    @app.post(
        "/api/jobs/{job_id}/scenes/pressure",
        status_code=status.HTTP_201_CREATED,
    )
    def build_pressure_scene(
        job_id: str,
        field: str = "cp",
        range_min: float | None = None,
        range_max: float | None = None,
    ) -> dict[str, object]:
        _get_or_404(service, job_id)
        try:
            return _public_snapshot(
                service.build_pressure_scene(
                    job_id, field, range_min=range_min, range_max=range_max
                )
            )
        except ValueError as error:
            raise _bad_request(str(error)) from None

    @app.post(
        "/api/jobs/{job_id}/scenes/y-plus",
        status_code=status.HTTP_201_CREATED,
    )
    def build_y_plus_scene(
        job_id: str,
        range_min: float | None = None,
        range_max: float | None = None,
    ) -> dict[str, object]:
        _get_or_404(service, job_id)
        try:
            return _public_snapshot(
                service.build_y_plus_scene(
                    job_id, range_min=range_min, range_max=range_max
                )
            )
        except ValueError as error:
            code = str(error)
            if code in {"Y_PLUS_EVIDENCE_UNAVAILABLE", "Y_PLUS_FIELD_MISSING"}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": code},
                ) from None
            raise _bad_request(code) from None

    @app.post(
        "/api/jobs/{job_id}/scenes/velocity",
        status_code=status.HTTP_201_CREATED,
    )
    def build_velocity_scene(
        job_id: str,
        preset: str = "longitudinal",
        position: float = 0.0,
        opacity: float = 1.0,
        visible: bool = True,
    ) -> dict[str, object]:
        _get_or_404(service, job_id)
        try:
            return _public_snapshot(
                service.build_velocity_scene(
                    job_id,
                    preset,
                    position=position,
                    opacity=opacity,
                    visible=visible,
                )
            )
        except ValueError as error:
            raise _bad_request(str(error)) from None

    @app.post(
        "/api/jobs/{job_id}/scenes/streamlines",
        status_code=status.HTTP_201_CREATED,
    )
    def build_streamline_scene(
        job_id: str,
        density: str = "standard",
        line_width: float = 3.0,
        opacity: float = 1.0,
        visible: bool = True,
    ) -> dict[str, object]:
        _get_or_404(service, job_id)
        try:
            return _public_snapshot(
                service.build_streamline_scene(
                    job_id,
                    density,
                    line_width=line_width,
                    opacity=opacity,
                    visible=visible,
                )
            )
        except (KeyError, ValueError) as error:
            raise _bad_request(str(error)) from None

    @app.get("/api/jobs/{job_id}/artifacts/{artifact_name}")
    def get_artifact(job_id: str, artifact_name: str) -> FileResponse:
        snapshot = _get_or_404(service, job_id)
        selected = dict(snapshot.artifacts or {}).get(artifact_name)
        if selected is None:
            raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND"})
        path = Path(selected).resolve(strict=False)
        if not path.is_relative_to(snapshot.job_directory) or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND"})
        if path.suffix.casefold() == ".html":
            return FileResponse(path, media_type="text/html")
        return FileResponse(path, filename=artifact_name)

    return app


def _production_job_service(project_root: Path) -> LocalJobService:
    config_path = project_root / "config" / "local_tools.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        su2 = Path(config["su2_cfd_executable"]).resolve(strict=True)
        su2_version = str(config["su2_version"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        raise RuntimeError("WEB_SU2_CONFIGURATION_INVALID") from None
    versions = {
        "Phoenix Aero Lite": _version("phoenix-aero-lite"),
        "Gmsh": _version("gmsh"),
        "SU2": su2_version,
        "meshio": _version("meshio"),
        "PyVista": _version("pyvista"),
    }
    cache_root = project_root / "web-data" / "pipeline-cache"
    cache_max_bytes = 20 * 1024**3

    def runner(
        source,
        parameters,
        _case_root,
        cancellation,
        progress_callback,
        *,
        producer_id,
    ):
        enforce_cache_limit(cache_root, max_bytes=cache_max_bytes)
        pipeline = PhoenixCasePipeline(
            su2_cfd_executable=su2,
            software_versions=versions,
            solver_timeout_s=3 * 60 * 60,
        )
        lease = acquire_cache_run_lease(
            pipeline.cache_run_root(source, parameters, cache_root)
        )
        try:
            result = pipeline.run(
                source,
                parameters,
                cache_root,
                cancellation=cancellation,
                progress_callback=progress_callback,
                producer_id=producer_id,
            )
        except BaseException:
            lease.release()
            raise
        return replace(result, cache_lease=lease)

    return LocalJobService(
        project_root / "web-data" / "jobs",
        runner=runner,
        cache_policy={
            "max_bytes": cache_max_bytes,
            "cleanup_policy": "oldest-run-first",
        },
        cache_cleanup=lambda: enforce_cache_limit(
            cache_root,
            max_bytes=cache_max_bytes,
        ),
    )


def _version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unknown"


def _get_or_404(service: LocalJobService, job_id: str) -> JobSnapshot:
    try:
        return service.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"}) from None


def _get_grid_study_or_404(
    service: LocalGridStudyService, study_id: str
) -> GridStudySnapshot:
    try:
        return service.get(study_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail={"code": "GRID_STUDY_NOT_FOUND"}
        ) from None


def _public_grid_study(snapshot: GridStudySnapshot) -> dict[str, object]:
    payload = snapshot.to_dict()
    payload.pop("study_directory", None)
    return payload


def _get_model_or_404(
    service: LocalModelService, model_id: str
) -> ModelSnapshot:
    try:
        return service.get(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND"}) from None


def _bad_request(code: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code})


def _public_snapshot(snapshot: JobSnapshot) -> dict[str, object]:
    payload = snapshot.to_dict()
    payload.pop("job_directory", None)
    payload["artifacts"] = {
        name: f"/api/jobs/{snapshot.job_id}/artifacts/{name}"
        for name in (snapshot.artifacts or {})
    }
    payload["aerodynamic_summary"] = _aerodynamic_summary(snapshot)
    codes = tuple(
        value
        for value in (snapshot.error_code, *snapshot.credibility_reason_codes)
        if value
    )
    diagnostics = diagnostics_for_codes(codes)
    payload["user_diagnostics"] = [item.to_dict() for item in diagnostics]
    payload["conservative_retry_available"] = bool(
        snapshot.state.is_terminal
        and snapshot.retry_attempt < 1
        and any(item.conservative_retry_allowed for item in diagnostics)
    )
    return payload


def _aerodynamic_summary(snapshot: JobSnapshot) -> dict[str, object]:
    request = snapshot.request
    try:
        dynamic_pressure = (
            0.5
            * float(request["density_kg_m3"])
            * float(request["velocity_m_s"]) ** 2
        )
        area = float(request["s_ref_m2"])
        weight = float(request["mass_kg"]) * 9.80665
    except (KeyError, TypeError, ValueError):
        return {}
    cl = snapshot.cl
    cd = snapshot.cd
    lift = dynamic_pressure * area * cl if cl is not None and math.isfinite(cl) else None
    drag = dynamic_pressure * area * cd if cd is not None and math.isfinite(cd) else None
    ratio = lift / weight if lift is not None and weight > 0 else None
    return {
        "dynamic_pressure_pa": dynamic_pressure,
        "lift_n": lift,
        "drag_n": drag,
        "weight_n": weight,
        "lift_weight_ratio": ratio,
        "takeoff_boundary_zh": (
            "升力达到重量不等于已经证明飞机能够实际起飞；"
            "还要考虑推力、地面加速、姿态、控制和安全余量。"
        ),
    }


def _public_model(snapshot: ModelSnapshot) -> dict[str, object]:
    payload = snapshot.to_dict()
    payload.pop("model_directory", None)
    payload["artifacts"] = {
        name: f"/api/models/{snapshot.model_id}/artifacts/{name}"
        for name in snapshot.artifacts
    }
    return payload
