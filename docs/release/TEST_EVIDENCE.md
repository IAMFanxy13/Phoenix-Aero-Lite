# Test evidence

All final commands are executed on Windows 11, Python 3.12, Gmsh 4.15.2, PyVista 0.48.4 and official SU2 8.5.0. Machine-specific paths and private CAD are intentionally excluded from the public source export.

## Software verification

| Gate | Final observed result | Evidence meaning |
|---|---|---|
| Full development-tree pytest | 400 passed, 2 skipped | Unit, local integration and both headless Chromium workflows |
| Non-E2E pytest | 398 passed, 2 skipped, 2 deselected | Unit, API, Gmsh, visualization, recovery, security and packaging behavior |
| Playwright E2E | 2 passed | Real Chromium interaction with public OCC STEP, picking, correction, jobs, cancel/failure/restart, Cp/Pa/Y+, slices, streamlines and report |
| Public-tree pytest | 365 passed, 35 skipped | History-free source and both headless browser workflows work; machine-only SU2 tests skip explicitly when local configuration is absent |
| Ruff | PASS | Selected Python lint rules |
| mypy | PASS | Core scientific and manifest modules |
| compileall | PASS | Source and tests compile |
| Bandit high severity | PASS | No high-severity Python finding |
| pip check | PASS | Installed dependency consistency |
| pip-audit | PASS | No known vulnerability in the pinned environment at verification time |
| wheel + sdist | PASS | PEP 517 build completed |
| Clean wheel import | PASS | `0.1.0.dev0` installed with `--no-deps` in a new virtual environment and imported |
| License files in archives | PASS | `LICENSE`, `THIRD_PARTY_NOTICES.md`, `LICENSES/README.md` present in wheel and sdist |
| Source launcher | PASS | check-only, port-conflict exit 16, loopback health, runtime-crash diagnosis, Ctrl+C cleanup and zero remaining listener |
| PyInstaller | PASS for internal evaluation | Clean build; hidden `run-case` smoke returned exit 2 plus structured `HEADLESS_INPUT_NOT_FOUND` rather than a DLL/runtime crash |
| Public sensitive scan | PASS | No Git history, private model hash, local path, username, token or private CAD finding |

Warnings are primarily VTK/Trame deprecations and one Starlette TestClient deprecation. They are recorded but are not test failures.

## Real official benchmark

Source: official SU2 v8.5.0 `rans/naca0012/turb_NACA0012_sst.cfg` and official TestCases mesh family. Each level used at most 3000 iterations and one OpenMP solver thread per process invocation configuration.

| Grid | Nodes | Cells | CL | CD | L/D | Time | Convergence |
|---|---:|---:|---:|---:|---:|---:|---|
| Coarse | 3,704 | 3,584 | 0.8909763798 | 0.05924331344 | 15.0393 | 15.34 s | converged |
| Medium | 14,576 | 14,336 | 1.070412897 | 0.01577481509 | 67.8558 | 82.25 s | converged |
| Fine | 57,824 | 57,344 | 1.083985252 | 0.01303191381 | 83.1793 | 340.41 s | converged |

Fine-grid GCI: CL 0.1281%, CD 1.7720%, L/D 9.4115%. The three quantities were monotonic and passed the implemented asymptotic-range gate. This is L3 numerical verification only; it is not experimental validation.

## Private diagnostic evidence

- Geometry: 1 volume, 62 surfaces; surface 35 was the coarse surface-mesh warning location.
- Repair strategy: official OCC import/deduplication and Gmsh Frontal-Delaunay refinement at 0.04 m; no source modification.
- Solver execution: completed with real history and fields.
- Convergence: stagnated.
- Y+: computed from solver wall data; P95 290.62, 99.845% outside the resolved-wall target.
- Scientific result: diagnostic/caution; coefficients not usable for engineering; no take-off claim.

## Browser evidence

- `artifacts/e2e/public_workbench_surface_selected.png`
- `artifacts/e2e/public_workbench_y_plus.png`
- Browser console/page error record: empty.

The E2E solution fields are explicitly synthetic public fixtures used to test visualization and permissions, not physical validation data.
