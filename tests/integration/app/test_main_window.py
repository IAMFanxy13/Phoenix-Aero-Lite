from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from phoenix_aero_lite.app.main_window import MainWindow
from phoenix_aero_lite.app.workflow_state import WorkflowStage
from phoenix_aero_lite.models.parameters import MeshMode


def test_main_window_has_four_chinese_regions_and_stable_controls(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    model = tmp_path / "air.step"
    model.write_text("fixture", encoding="utf-8")
    window = MainWindow()
    try:
        for name in (
            "modelGroup",
            "parameterGroup",
            "progressGroup",
            "resultGroup",
            "inspectGeometryButton",
            "meshButton",
            "solveButton",
            "cancelButton",
            "reportButton",
            "resultTabs",
        ):
            assert window.findChild(QWidget, name) is not None
        assert window.select_model(model)
        assert window.workflow_state.stage is WorkflowStage.MODEL_SELECTED
        window.inspection_succeeded("尺寸：2 × 1 × 0.5 m", "实体：1")
        assert window.mesh_button.isEnabled()
        window.mesh_button.click()
        assert window.workflow_state.stage is WorkflowStage.MESHING
        assert not window.parameter_form.isEnabled()
        assert window.cancel_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_parameter_form_normalizes_frozen_qt_mesh_mode_data():
    """PyInstaller/Qt may restore str-enum item data as its string value."""

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.parameter_form.mesh_mode.setItemData(0, MeshMode.PREVIEW.value)

        parameters = window.parameter_form.case_parameters()

        assert parameters.mesh.mode is MeshMode.PREVIEW
        assert parameters.mesh.validate() == ()
    finally:
        window.close()
        app.processEvents()


def test_lite_release_only_offers_validated_preview_mesh_mode():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        selector = window.parameter_form.mesh_mode
        assert selector.count() == 1
        assert MeshMode(selector.itemData(0)) is MeshMode.PREVIEW
        assert "预览" in selector.itemText(0)
        assert "标准" in selector.toolTip()
    finally:
        window.close()
        app.processEvents()
