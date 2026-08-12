# Phoenix Aero Lite final completion report

Date: 2026-08-04  
Branch: `feature/product-ux`  
Release status: source-deliverable pre-release; not a certification or flight-safety tool.

## Outcome

Phoenix Aero Lite now provides one local Windows workflow for STEP/STP inspection, real OpenCASCADE/Gmsh meshing, SU2 execution, scientific gating, browser-based VTK result review, persistent jobs, conservative retry, three-grid studies and reproducible reports. It reuses official/mature upstream APIs rather than implementing CAD, CFD, meshing or rendering kernels.

“Completed” means the software path is implemented and verified. It does not mean every CAD is guaranteed to mesh or converge, and it does not promote a diagnostic CFD field to an engineering conclusion.

## Implemented and verified

| Area | Delivered behavior | Verification class |
|---|---|---|
| Geometry | STEP/STP upload, OCC inspection, units/dimensions, scale/topology diagnostics, public 3D preview | Public synthetic OCC + integration + browser E2E |
| Human correction | Real VTK surface picking/highlight, multi-select/toggle/reset/undo, orientation candidates, surface tags, reference area/chord/span recomputation, original/current/override provenance | Public browser E2E + API/unit tests |
| Mesh | External domain, physical groups, local refinement, official Gmsh 3D boundary-layer extrusion, wedge/prism counts and quality gates | Gmsh integration tests + private model audit |
| Solver | Official SU2 8.5.0 external process, timeout/cancel/process-tree cleanup, stdout/stderr/exit capture | Official SU2 runs + unit/integration tests |
| Scientific evidence | Execution and convergence are orthogonal; quantity-level provenance, Y+ estimated/computed distinction, credibility and validation levels | Unit regression + real official histories |
| Results | Real Cp/static pressure, Y+, velocity slices and flow-field streamlines; ranges, presets, views, screenshot/fullscreen and Chinese failure states | Public VTK browser E2E; no placeholder fields |
| Recovery | Atomic manifests/jobs, restart classification, stage checkpoints, SHA-256 validation, shared model cache, 20 GiB oldest-run-first policy, cross-process active-run leases, per-job result materialization | Unit/API/restart/E2E tests |
| Product UX | Four-task compact workbench, icon+text state, folded professional evidence, presets, stage progress and actionable diagnostics | Browser E2E and accessibility assertions |
| Windows | Double-click launcher, dependency/SU2/port checks, hidden loopback backend, health wait, runtime-failure diagnosis and shutdown cleanup | Source launcher smoke + internal PyInstaller headless smoke |
| Open source | GPL-3.0-or-later metadata, notices, community files, GitHub dry-run workflows and history-free public export | Package build, sensitive scan and public-tree regression |

## Scientific validation

- L1: official SU2 QuickStart and INC_RANS/SST regression paths execute with official inputs.
- L3: the official SU2 v8.5.0 NACA0012 SST grid family was run at three resolutions. All three runs converged and the GCI gates were computed from real histories.
- No L4/L5 experimental validation is claimed. The public L3 study checks numerical implementation and grid sensitivity, not agreement with wind-tunnel data.
- The validation level of a benchmark is never inherited by a user model.

## Private model status

The original private STEP and SolidWorks files remain outside the project and unchanged. The surface warning was localized to surface 35; an official Frontal-Delaunay strategy at 0.04 m removed the invalid-element warning without changing OCC volume/surface counts or source files. The representative SU2 execution completed, but convergence stagnated and the computed wall Y+ P95 was 290.62 with 99.845% of area outside the resolved-wall target. Therefore coefficients are diagnostic-only, `coefficients_usable=false`, and no take-off conclusion is permitted.

## Distribution decision

- Recommended public artifact: the history-free source export, wheel and sdist.
- Internal/evaluation artifact: the PyInstaller directory. It starts without the previously observed mypyc/DLL failure, but it must not be published until all bundled native license/NOTICE texts are collected.
- No repository, Release, package index or remote branch was created or pushed.

## Evidence

Detailed command results are in `docs/release/TEST_EVIDENCE.md`; scope limits are in `docs/release/KNOWN_LIMITATIONS.md`; the maintainer’s manual publication steps are in `docs/release/PUBLICATION_CHECKLIST.md`.
