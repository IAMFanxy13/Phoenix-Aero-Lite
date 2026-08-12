"""Read-only Chinese workflow log panel."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout


class LogPanel(QWidget):
    """Timestamped plain-text log without rich-text injection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("logPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text = QPlainTextEdit()
        self.text.setObjectName("workflowLog")
        self.text.setReadOnly(True)
        layout.addWidget(self.text)

    def append_info(self, message: str) -> None:
        self._append("信息", message)

    def append_error(self, message: str) -> None:
        self._append("错误", message)

    def _append(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.text.appendPlainText(f"[{timestamp}] [{level}] {message}")
