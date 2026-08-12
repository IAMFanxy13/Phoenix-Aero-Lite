from __future__ import annotations

import importlib
import os
import sys


def test_import_does_not_force_qt_platform(monkeypatch):
    module_name = "scripts.research.validate_qt_pyvista_embed"
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    sys.modules.pop(module_name, None)

    importlib.import_module(module_name)

    assert "QT_QPA_PLATFORM" not in os.environ
