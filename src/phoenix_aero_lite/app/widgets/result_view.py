"""PySide6/PyVistaQt result widget for Phoenix Aero Lite."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from phoenix_aero_lite.postprocess.pyvista_results import (
    PyVistaResultError,
    ResultDataset,
    load_result,
)


_MESSAGES_ZH = {
    "RESULT_SCALAR_MISSING": "结果中没有所选标量场。",
    "RESULT_VECTOR_MISSING": "结果中没有速度矢量，无法生成流线。",
    "STREAMLINES_EMPTY": "当前种子位置没有生成有效流线。",
    "STREAMLINE_SEED_COUNT_INVALID": "流线种子数量必须在 1 到 10000 之间。",
    "RESULT_FILE_MISSING": "结果文件不存在。",
    "RESULT_READ_FAILED": "结果文件无法由 PyVista 读取。",
}


class ResultView(QWidget):
    """Embeddable interactive CFD view backed only by PyVistaQt."""

    error_message = Signal(str)
    result_loaded = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.interactor = QtInteractor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.interactor)
        self._result: ResultDataset | None = None

    @property
    def result(self) -> ResultDataset | None:
        """Currently loaded immutable result wrapper."""

        return self._result

    def load_file(self, path: Path) -> bool:
        """Load and display one VTK/VTU result, reporting Chinese errors."""

        try:
            self._result = load_result(path)
            self.show_volume()
        except PyVistaResultError as error:
            self._emit_error(error)
            return False
        self.result_loaded.emit(self._result)
        return True

    def show_volume(self, scalars: str | None = None) -> bool:
        """Display the full dataset."""

        if not self._require_result():
            return False
        try:
            if scalars is not None and scalars not in self._result.scalar_names:
                raise PyVistaResultError("RESULT_SCALAR_MISSING")
            self.interactor.clear()
            self.interactor.add_mesh(self._result.dataset, scalars=scalars)
            self.interactor.reset_camera()
            return True
        except PyVistaResultError as error:
            self._emit_error(error)
            return False

    def show_slice(self) -> bool:
        """Display a central x-normal slice."""

        return self._display_operation(lambda: self._result.slice())

    def show_clip(self) -> bool:
        """Display a central x-normal clip."""

        return self._display_operation(lambda: self._result.clip())

    def show_contour(self, scalar: str, count: int = 10) -> bool:
        """Display scalar isosurfaces."""

        return self._display_operation(
            lambda: self._result.contour(scalar, count=count)
        )

    def show_streamlines(self, vector: str, seed_count: int = 100) -> bool:
        """Display bounded PyVista streamlines."""

        return self._display_operation(
            lambda: self._result.streamlines(
                vector, seed_count=seed_count
            )
        )

    def save_screenshot(
        self,
        output_path: Path,
        scalars: str | None = None,
    ) -> bool:
        """Save a deterministic off-screen evidence image."""

        if not self._require_result():
            return False
        try:
            self._result.screenshot(output_path, scalars=scalars)
            return True
        except PyVistaResultError as error:
            self._emit_error(error)
            return False

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.interactor.close()
        super().closeEvent(event)

    def _display_operation(self, operation) -> bool:
        if not self._require_result():
            return False
        try:
            geometry = operation()
            self.interactor.clear()
            self.interactor.add_mesh(geometry)
            self.interactor.reset_camera()
            return True
        except PyVistaResultError as error:
            self._emit_error(error)
            return False

    def _require_result(self) -> bool:
        if self._result is None:
            self.error_message.emit("请先加载 CFD 结果文件。")
            return False
        return True

    def _emit_error(self, error: PyVistaResultError) -> None:
        code = str(error)
        self.error_message.emit(_MESSAGES_ZH.get(code, f"结果处理失败：{code}"))
