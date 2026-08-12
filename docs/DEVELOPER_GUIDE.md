# Developer Guide

Use Python 3.12 and an isolated Git worktree. From the project root:

```powershell
$env:PYTHONPATH = 'src'
$env:PYVISTA_OFF_SCREEN = 'true'
python -m pytest -q
python -m compileall -q src tests
python -m pip check
```

New behaviour follows red–green–refactor. Never replace Gmsh, SU2, meshio, PyVista or VTK with private parsers/engines. Local tests may use private CAD, but public tests and examples must use licensed public or explicitly synthetic fixtures. Keep commits focused and retain machine error codes behind the Chinese diagnostic layer.

See [Architecture](ARCHITECTURE.md), [Reproducibility](REPRODUCIBILITY.md), [Contributing](../CONTRIBUTING.md) and the [threat model](security/THREAT_MODEL.md).
