"""Single-page Chinese Phoenix Aero Lite desktop shell."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from phoenix_aero_lite.app.widgets.log_panel import LogPanel
from phoenix_aero_lite.app.widgets.parameter_form import ParameterForm
from phoenix_aero_lite.app.widgets.result_view import ResultView
from phoenix_aero_lite.app.workflow_state import (
    WorkflowEvent,
    WorkflowStage,
    WorkflowState,
    initial_workflow_state,
    transition,
)
from phoenix_aero_lite.models.results import AerodynamicSummary


class MainWindow(QMainWindow):
    """Four-quadrant GUI that emits commands and only presents workflow state."""

    inspect_requested = Signal(object)
    mesh_requested = Signal(object)
    solve_requested = Signal(object)
    cancel_requested = Signal()
    report_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("Phoenix Aero Lite")
        self.resize(1440, 900)
        self._state = initial_workflow_state()
        self._model_path: Path | None = None
        self.result_view: ResultView | None = None
        central = QWidget()
        central.setObjectName("centralWorkflowPage")
        grid = QGridLayout(central)
        grid.addWidget(self._build_model_group(), 0, 0)
        grid.addWidget(self._build_parameter_group(), 0, 1)
        grid.addWidget(self._build_progress_group(), 1, 0)
        grid.addWidget(self._build_result_group(), 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("请选择 STEP 模型")
        self._apply_state()

    @property
    def workflow_state(self) -> WorkflowState:
        return self._state

    def select_model(self, path: Path) -> bool:
        """Select, but never modify, a STEP source model."""

        if (
            not isinstance(path, Path)
            or not path.is_file()
            or path.suffix.lower() not in {".step", ".stp"}
        ):
            self.log_panel.append_error("请选择存在的 STEP 文件。")
            return False
        self._model_path = path.resolve(strict=True)
        self.model_path_edit.setText(str(self._model_path))
        self._state = transition(self._state, WorkflowEvent.MODEL_SELECTED)
        self.log_panel.append_info("已选择 STEP 模型，等待几何检查。")
        self._apply_state()
        return True

    def inspection_succeeded(
        self,
        dimensions_text: str,
        entity_text: str,
    ) -> None:
        self.dimensions_label.setText(dimensions_text)
        self.entities_label.setText(entity_text)
        self._advance(WorkflowEvent.INSPECTION_SUCCEEDED, "几何检查通过。")

    def operation_failed(self, event: WorkflowEvent, message: str) -> None:
        self._state = transition(self._state, event, message)
        self.log_panel.append_error(message)
        self._apply_state()

    def mesh_succeeded(self) -> None:
        self._advance(WorkflowEvent.MESH_SUCCEEDED, "网格生成完成。")

    def solve_succeeded(self) -> None:
        self._advance(WorkflowEvent.SOLVE_SUCCEEDED, "SU2 求解完成，开始后处理。")

    def postprocess_succeeded(self) -> None:
        self._advance(WorkflowEvent.POSTPROCESS_SUCCEEDED, "结果和报告已生成。")

    def present_aerodynamics(self, summary: AerodynamicSummary) -> None:
        """Display loads only when the convergence gate made them valid."""

        if summary.valid:
            assert summary.cl and summary.cd and summary.lift and summary.drag
            assert summary.lift_margin
            self.coefficient_label.setText(
                f"CL：{summary.cl.value:.6g}   CD：{summary.cd.value:.6g}"
            )
            self.force_label.setText(
                f"升力：{summary.lift.value:.6g} N    "
                f"阻力：{summary.drag.value:.6g} N"
            )
            decision = "满足" if summary.meets_weight_requirement else "不满足"
            self.margin_label.setText(
                f"重量：{summary.weight.value:.6g} N    "
                f"裕度：{summary.lift_margin.value:.6g} N    判断：{decision}"
            )
        else:
            if summary.cl is not None and summary.cd is not None:
                self.coefficient_label.setText(
                    f"未收敛预估 CL：{summary.cl.value:.6g}   "
                    f"CD：{summary.cd.value:.6g}"
                )
            else:
                self.coefficient_label.setText("CL：—   CD：—")
            self.force_label.setText("升力：无效    阻力：无效")
            self.margin_label.setText(
                f"重量：{summary.weight.value:.6g} N    "
                f"判断：CFD 未收敛（{summary.reason_code}）"
            )

    def load_result_file(self, path: Path) -> bool:
        """Lazily create the OpenGL view only when a result is available."""

        view = self._ensure_result_view()
        return view.load_file(path)

    def reset_after_failure_or_cancel(self) -> None:
        self._advance(WorkflowEvent.RESET, "工作流已恢复，可重新执行。")

    def _build_model_group(self) -> QGroupBox:
        group = QGroupBox("模型与几何")
        group.setObjectName("modelGroup")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.model_path_edit = QLineEdit()
        self.model_path_edit.setObjectName("modelPathInput")
        self.model_path_edit.setReadOnly(True)
        self.choose_model_button = QPushButton("选择 STEP")
        self.choose_model_button.setObjectName("chooseModelButton")
        self.choose_model_button.clicked.connect(self._choose_model)
        row.addWidget(self.model_path_edit)
        row.addWidget(self.choose_model_button)
        layout.addLayout(row)
        self.dimensions_label = QLabel("尺寸：—")
        self.dimensions_label.setObjectName("dimensionsLabel")
        self.entities_label = QLabel("实体：—")
        self.entities_label.setObjectName("entitiesLabel")
        self.unit_label = QLabel("单位：m（导入后按 OCC 几何检查）")
        self.unit_label.setObjectName("unitLabel")
        layout.addWidget(self.dimensions_label)
        layout.addWidget(self.entities_label)
        layout.addWidget(self.unit_label)
        preview = QLabel("三维模型预览将在几何检查完成后显示")
        preview.setObjectName("modelPreview")
        preview.setMinimumHeight(130)
        preview.setStyleSheet("background:#101827;color:#cbd5e1;padding:18px;")
        layout.addWidget(preview)
        self.inspect_button = QPushButton("检查几何")
        self.inspect_button.setObjectName("inspectGeometryButton")
        self.inspect_button.clicked.connect(self._request_inspection)
        layout.addWidget(self.inspect_button)
        return group

    def _build_parameter_group(self) -> QGroupBox:
        group = QGroupBox("流场与计算参数")
        group.setObjectName("parameterGroup")
        layout = QVBoxLayout(group)
        self.parameter_form = ParameterForm()
        layout.addWidget(self.parameter_form)
        return group

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("计算进度与日志")
        group.setObjectName("progressGroup")
        layout = QVBoxLayout(group)
        self.progress = QProgressBar()
        self.progress.setObjectName("workflowProgress")
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.mesh_button = QPushButton("生成网格")
        self.mesh_button.setObjectName("meshButton")
        self.solve_button = QPushButton("运行 SU2")
        self.solve_button.setObjectName("solveButton")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancelButton")
        self.mesh_button.clicked.connect(self._request_mesh)
        self.solve_button.clicked.connect(self._request_solve)
        self.cancel_button.clicked.connect(self._request_cancel)
        buttons.addWidget(self.mesh_button)
        buttons.addWidget(self.solve_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.log_panel = LogPanel()
        layout.addWidget(self.log_panel)
        return group

    def _build_result_group(self) -> QGroupBox:
        group = QGroupBox("结果与报告")
        group.setObjectName("resultGroup")
        layout = QVBoxLayout(group)
        self.coefficient_label = QLabel("CL：—    CD：—")
        self.coefficient_label.setObjectName("coefficientLabel")
        self.force_label = QLabel("升力：— N    阻力：— N")
        self.force_label.setObjectName("forceLabel")
        self.margin_label = QLabel("重量：— N    裕度：— N    判断：—")
        self.margin_label.setObjectName("marginLabel")
        layout.addWidget(self.coefficient_label)
        layout.addWidget(self.force_label)
        layout.addWidget(self.margin_label)
        self.result_tabs = QTabWidget()
        self.result_tabs.setObjectName("resultTabs")
        self.pressure_placeholder = QLabel("压力结果将在求解后加载")
        self.pressure_placeholder.setObjectName("pressureTab")
        self.result_tabs.addTab(self.pressure_placeholder, "压力")
        for object_name, title in (
            ("velocityTab", "速度"),
            ("streamlineTab", "流线"),
            ("turbulenceTab", "湍流"),
        ):
            placeholder = QLabel(f"{title}结果将在求解后加载")
            placeholder.setObjectName(object_name)
            self.result_tabs.addTab(placeholder, title)
        layout.addWidget(self.result_tabs)
        self.report_button = QPushButton("打开 / 生成报告")
        self.report_button.setObjectName("reportButton")
        self.report_button.clicked.connect(
            lambda _checked=False: self.report_requested.emit()
        )
        layout.addWidget(self.report_button)
        return group

    def _ensure_result_view(self) -> ResultView:
        if self.result_view is None:
            self.result_view = ResultView()
            self.result_view.setObjectName("pressureResultView")
            self.result_tabs.removeTab(0)
            self.pressure_placeholder.setParent(None)
            self.result_tabs.insertTab(0, self.result_view, "压力")
            self.result_tabs.setCurrentIndex(0)
        return self.result_view

    def _choose_model(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择 STEP 模型",
            "",
            "STEP 模型 (*.step *.stp)",
        )
        if filename:
            self.select_model(Path(filename))

    def _request_inspection(self) -> None:
        if self._model_path is not None:
            self.inspect_requested.emit(self._model_path)

    def _request_mesh(self) -> None:
        self._state = transition(self._state, WorkflowEvent.MESH_STARTED)
        self._apply_state()
        self.log_panel.append_info("网格任务已提交到后台。")
        self.mesh_requested.emit(self.parameter_form.case_parameters())

    def _request_solve(self) -> None:
        self._state = transition(self._state, WorkflowEvent.SOLVE_STARTED)
        self._apply_state()
        self.log_panel.append_info("SU2 任务已提交到后台。")
        self.solve_requested.emit(self.parameter_form.case_parameters())

    def _request_cancel(self) -> None:
        self._state = transition(self._state, WorkflowEvent.CANCEL)
        self._apply_state()
        self.log_panel.append_info("已请求取消当前任务。")
        self.cancel_requested.emit()

    def _advance(self, event: WorkflowEvent, message: str) -> None:
        self._state = transition(self._state, event)
        self.log_panel.append_info(message)
        self._apply_state()

    def _apply_state(self) -> None:
        self.parameter_form.set_locked(not self._state.can_edit_parameters)
        self.choose_model_button.setEnabled(
            self._state.can_edit_parameters
        )
        self.inspect_button.setEnabled(
            self._state.stage is WorkflowStage.MODEL_SELECTED
        )
        self.mesh_button.setEnabled(self._state.can_mesh)
        self.solve_button.setEnabled(self._state.can_solve)
        self.cancel_button.setEnabled(self._state.can_cancel)
        self.report_button.setEnabled(
            self._state.stage is WorkflowStage.COMPLETED
        )
        progress = {
            WorkflowStage.EMPTY: 0,
            WorkflowStage.MODEL_SELECTED: 0,
            WorkflowStage.GEOMETRY_READY: 1,
            WorkflowStage.MESHING: 2,
            WorkflowStage.MESH_READY: 2,
            WorkflowStage.SOLVING: 3,
            WorkflowStage.POSTPROCESSING: 4,
            WorkflowStage.COMPLETED: 5,
        }.get(self._state.stage, self.progress.value())
        self.progress.setValue(progress)
        self.statusBar().showMessage(self._state.stage.value)
