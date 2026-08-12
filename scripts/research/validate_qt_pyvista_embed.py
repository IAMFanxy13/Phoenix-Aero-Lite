"""Exercise the documented PySide6 + PyVistaQt embedding path off-screen."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    frame = QFrame()
    layout = QVBoxLayout(frame)
    plotter = QtInteractor(frame, off_screen=True)
    layout.addWidget(plotter.interactor)
    plotter.add_mesh(pv.Sphere(theta_resolution=48, phi_resolution=48), color="steelblue")
    plotter.reset_camera()
    frame.resize(640, 480)
    frame.show()
    app.processEvents()

    screenshot = args.output_dir / "pyside6_pyvista_embed.png"
    plotter.screenshot(str(screenshot))
    plotter.close()
    frame.close()

    result = {
        "qt_api": os.environ["QT_API"],
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", "Qt default"),
        "pyvista_version": pv.__version__,
        "screenshot": str(screenshot.resolve()),
        "screenshot_bytes": screenshot.stat().st_size,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
