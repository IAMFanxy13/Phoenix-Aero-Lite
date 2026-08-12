"""Connect the desktop shell to the real reusable CFD adapters."""

from __future__ import annotations

import importlib
from importlib import metadata
from pathlib import Path
import webbrowser
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from phoenix_aero_lite.app.pipeline import PhoenixCasePipeline
from phoenix_aero_lite.app.workflow_state import WorkflowEvent, WorkflowStage
from phoenix_aero_lite.geometry.gmsh_geometry import GmshGeometryAdapter
from phoenix_aero_lite.meshing.gmsh_mesher import GmshMesher
from phoenix_aero_lite.models.parameters import CaseParameters
from phoenix_aero_lite.utilities.process_runner import CancellationToken
from phoenix_aero_lite.utilities.runtime_discovery import discover_runtime


def _package_version(name: str) -> str:
    """Read a version even when PyInstaller omitted distribution metadata."""

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(name)
        return str(getattr(module, "__version__", "unknown"))


def _new_gui_mesh_output_directory(case_root: Path) -> Path:
    """Return a fresh publication target so an old mesh is never replaced."""

    return Path(case_root) / "gui_mesh_runs" / f"mesh-{uuid4().hex}"


def _format_error_chain(error: BaseException) -> str:
    """Keep stable wrapper codes and their actionable underlying exception."""

    messages: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " <- ".join(messages)


class _WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _Worker(QRunnable):
    def __init__(self, operation) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as error:
            self.signals.failed.emit(_format_error_chain(error))


class DesktopController(QObject):
    """Run CAD, mesh, and solver work off the Qt UI thread."""

    def __init__(self, window, project_root: Path) -> None:
        super().__init__(window)
        self.window = window
        self.project_root = Path(project_root).resolve(strict=False)
        self.thread_pool = QThreadPool.globalInstance()
        self.source_step: Path | None = None
        self.report_path: Path | None = None
        self.cancellation = CancellationToken()
        self._workers: set[_Worker] = set()
        window.inspect_requested.connect(self.inspect)
        window.mesh_requested.connect(self.mesh)
        window.solve_requested.connect(self.solve)
        window.cancel_requested.connect(self.cancel)
        window.report_requested.connect(self.open_report)

    def _runtime(self):
        report = discover_runtime(self.project_root)
        if not report.ready or report.su2.path is None:
            raise RuntimeError(
                f"{report.su2.code}: {report.su2.message_zh}; "
                f"{report.gmsh.code}: {report.gmsh.message_zh}"
            )
        return report

    def _submit(self, operation, succeeded, failure_event) -> None:
        worker = _Worker(operation)
        self._workers.add(worker)

        def finish(value):
            self._workers.discard(worker)
            if self.window.workflow_state.stage is WorkflowStage.CANCELLED:
                return
            succeeded(value)

        def fail(message):
            self._workers.discard(worker)
            if self.window.workflow_state.stage is WorkflowStage.CANCELLED:
                return
            self.window.operation_failed(failure_event, message)

        worker.signals.succeeded.connect(finish)
        worker.signals.failed.connect(fail)
        self.thread_pool.start(worker)

    @Slot(object)
    def inspect(self, source: Path) -> None:
        self.source_step = Path(source).resolve(strict=True)

        def success(inspection):
            dimensions = " × ".join(f"{value:.6g}" for value in inspection.dimensions_m)
            self.window.inspection_succeeded(
                f"尺寸：{dimensions} m",
                f"实体：{inspection.volume_count}；曲面：{inspection.surface_count}",
            )

        self._submit(
            lambda: GmshGeometryAdapter().inspect_step(self.source_step),
            success,
            WorkflowEvent.INSPECTION_FAILED,
        )

    @Slot(object)
    def mesh(self, parameters: CaseParameters) -> None:
        source = self._require_source()
        case_root = self._case_root(parameters)

        def operation():
            runtime = self._runtime()
            return GmshMesher(su2_validator_path=runtime.su2.path).build_external_mesh(
                source,
                parameters.mesh,
                _new_gui_mesh_output_directory(case_root),
            )

        self._submit(
            operation,
            lambda _artifacts: self.window.mesh_succeeded(),
            WorkflowEvent.MESH_FAILED,
        )

    @Slot(object)
    def solve(self, parameters: CaseParameters) -> None:
        source = self._require_source()
        case_root = self._case_root(parameters)
        self.cancellation = CancellationToken()

        def operation():
            runtime = self._runtime()
            versions = {
                name: _package_version(name)
                for name in ("gmsh", "meshio", "pyvista", "PySide6")
            }
            versions["SU2"] = runtime.su2.version or "unknown"
            pipeline = PhoenixCasePipeline(
                su2_cfd_executable=runtime.su2.path,
                software_versions=versions,
            )
            return pipeline.run(
                source, parameters, case_root, cancellation=self.cancellation
            )

        def success(result):
            self.window.solve_succeeded()
            self.window.present_aerodynamics(result.context["aerodynamics"])
            self.window.load_result_file(result.context["flow_vtu"])
            self.report_path = result.context["report_path"]
            self.window.postprocess_succeeded()

        self._submit(operation, success, WorkflowEvent.SOLVE_FAILED)

    @Slot()
    def cancel(self) -> None:
        self.cancellation.cancel()

    @Slot()
    def open_report(self) -> None:
        if self.report_path is not None and self.report_path.is_file():
            webbrowser.open(self.report_path.resolve(strict=True).as_uri())

    def _require_source(self) -> Path:
        if self.source_step is None:
            raise RuntimeError("GUI_SOURCE_NOT_SELECTED")
        return self.source_step

    def _case_root(self, parameters: CaseParameters) -> Path:
        output = parameters.output.output_directory
        return (
            output.resolve(strict=False)
            if output.is_absolute()
            else (self.project_root / output).resolve(strict=False)
        )
