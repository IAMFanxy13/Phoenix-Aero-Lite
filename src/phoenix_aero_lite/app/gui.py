"""Phoenix Aero Lite desktop entry point."""

from __future__ import annotations

import sys
import os
from pathlib import Path

from phoenix_aero_lite.utilities.project_root import (
    resolve_project_root as _resolve_project_root,
)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the headless workflow before loading or constructing Qt."""

    arguments = list(sys.argv if argv is None else argv)
    if len(arguments) > 1 and arguments[1] == "run-case":
        from phoenix_aero_lite.cli import run_case

        return run_case(arguments[2:])
    return _start_desktop(arguments)


def _start_desktop(argv: list[str]) -> int:
    """Start the Chinese PySide6 desktop application."""

    from PySide6.QtWidgets import QApplication

    from phoenix_aero_lite.app.controller import DesktopController
    from phoenix_aero_lite.app.main_window import MainWindow

    application = QApplication.instance() or QApplication(argv)
    application.setApplicationName("Phoenix Aero Lite")
    window = MainWindow()
    configured_root = os.environ.get("PAL_PROJECT_ROOT")
    project_root = _resolve_project_root(
        configured_root=configured_root,
        executable_path=Path(sys.executable),
        cwd=Path.cwd(),
    )
    window.controller = DesktopController(window, project_root)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
