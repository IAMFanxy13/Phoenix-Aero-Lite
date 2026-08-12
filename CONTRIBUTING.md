# Contributing

Open an issue before a major behavior or physics change. Do not attach proprietary CAD or local solver outputs.

Use a feature branch/worktree, write a failing test first, make a focused change, run targeted tests and then the full regression. Preserve the Gmsh + SU2 + PyVista/VTK + FastAPI architecture unless evidence supports an approved change. Never replace missing CFD, Y+, GCI or convergence evidence with synthetic success data.

Required local checks:

```powershell
$env:PYTHONPATH = "src"
$env:PYVISTA_OFF_SCREEN = "true"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\audit_licenses.py
git diff --check
```

By contributing, you agree that your contribution is provided under GPL-3.0-or-later and that you have authority to submit it.
