"""Validated Chinese case-parameter form."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

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


class ParameterForm(QWidget):
    """SI-only parameter editor with stable object names for Qt tests."""

    parameters_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("parameterForm")
        layout = QFormLayout(self)
        self.velocity = self._double("velocityInput", 0.01, 1000.0, 15.0, 3)
        self.angle = self._double("angleInput", -45.0, 45.0, 6.0, 2)
        self.reference_area = self._double(
            "referenceAreaInput", 1e-6, 1e6, 1.0, 4
        )
        self.reference_chord = self._double(
            "referenceChordInput", 1e-6, 1e4, 1.0, 4
        )
        self.mass = self._double("massInput", 1e-6, 1e7, 1.0, 3)
        self.mesh_mode = QComboBox()
        self.mesh_mode.setObjectName("meshModeInput")
        self.mesh_mode.addItem("预览（已验证）", MeshMode.PREVIEW)
        self.mesh_mode.setToolTip(
            "Phoenix Aero Lite 当前仅开放已通过真实 example_model.STEP 验证的预览网格；"
            "标准/精细近壁层模式待成熟上游方案验证后再开放。"
        )
        self.target_cell_size = self._double(
            "targetCellSizeInput", 1e-5, 1000.0, 0.5, 4
        )
        self.max_iterations = QSpinBox()
        self.max_iterations.setObjectName("maxIterationsInput")
        self.max_iterations.setRange(1, 1_000_000)
        self.max_iterations.setValue(500)
        self.output_directory = QLineEdit()
        self.output_directory.setObjectName("outputDirectoryInput")
        self.output_directory.setText("cases/case-001")
        rows = (
            ("速度 (m/s)", self.velocity),
            ("迎角 (°)", self.angle),
            ("参考面积 S_ref (m²)", self.reference_area),
            ("参考弦长 c_ref (m)", self.reference_chord),
            ("质量 (kg)", self.mass),
            ("网格模式", self.mesh_mode),
            ("目标单元尺寸 (m)", self.target_cell_size),
            ("最大迭代数", self.max_iterations),
            ("输出目录", self.output_directory),
        )
        for label, widget in rows:
            layout.addRow(label, widget)
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                widget.valueChanged.connect(
                    lambda *_: self.parameters_changed.emit()
                )
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(
                    lambda *_: self.parameters_changed.emit()
                )
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(
                    lambda *_: self.parameters_changed.emit()
                )

    def case_parameters(self) -> CaseParameters:
        """Build the existing immutable SI parameter model."""

        return CaseParameters(
            flow=FlowParameters(
                velocity_m_s=self.velocity.value(),
                density_kg_m3=1.225,
                dynamic_viscosity_pa_s=1.7894e-5,
                angle_of_attack_deg=self.angle.value(),
            ),
            reference=ReferenceParameters(
                s_ref_m2=self.reference_area.value(),
                c_ref_m=self.reference_chord.value(),
            ),
            aircraft=AircraftParameters(mass_kg=self.mass.value()),
            mesh=MeshParameters(
                mode=MeshMode(self.mesh_mode.currentData()),
                target_cell_size_m=self.target_cell_size.value(),
            ),
            solver=SolverParameters(
                max_iterations=self.max_iterations.value()
            ),
            output=OutputParameters(
                output_directory=Path(self.output_directory.text())
            ),
        )

    def set_locked(self, locked: bool) -> None:
        """Prevent parameter mutation while meshing/solving/postprocessing."""

        self.setEnabled(not locked)

    @staticmethod
    def _double(
        name: str,
        minimum: float,
        maximum: float,
        value: float,
        decimals: int,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setObjectName(name)
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        return widget
