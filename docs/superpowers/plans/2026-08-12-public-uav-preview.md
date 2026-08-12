# Public UAV Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the block-shaped public browser fixture and cube Y+ surface with one reproducible small fixed-wing UAV in both README screenshots.

**Architecture:** Keep the public fixture inside the existing browser E2E test and build it only with official Gmsh/OpenCASCADE primitives and boolean operations. Derive the deterministic pressure and Y+ test surface from that same STEP through the production Gmsh preview adapter, so picking and result rendering exercise the real application paths without claiming physical validation.

**Tech Stack:** Python 3.12, Gmsh/OpenCASCADE Python API, PyVista/VTK, Playwright, pytest.

## Global Constraints

- Do not read, modify, copy, or publish the user's `Air.STEP`.
- Do not download or bundle a third-party aircraft model.
- Do not add a new CAD or rendering dependency.
- Keep all scalar fields explicitly described as deterministic visualization-test data.
- Both README screenshots must use the same generated STEP geometry.

---

### Task 1: Reproducible fixed-wing UAV STEP fixture

**Files:**
- Modify: `tests/e2e/test_public_workbench.py`

**Interfaces:**
- Consumes: `gmsh.model.occ` official primitives, extrusion, rotation and synchronization APIs
- Produces: `_public_synthetic_aircraft(path: Path) -> Path` containing a fuselage, nose, swept main wings, horizontal tail and vertical tail

- [ ] **Step 1: Add a failing UAV geometry test**

Add `test_public_synthetic_aircraft_has_uav_proportions` that imports the generated STEP through `GmshGeometryAdapter.inspect_step` and asserts at least six volumes, span greater than 2.6 m, length greater than 2.0 m, height greater than 0.45 m, and more than 25 surfaces.

- [ ] **Step 2: Run the new test and confirm the old block fixture fails**

Run:

```powershell
python -m pytest -q tests/e2e/test_public_workbench.py::test_public_synthetic_aircraft_has_uav_proportions
```

Expected: FAIL because the current fused box fixture is one shallow volume.

- [ ] **Step 3: Implement the UAV with Gmsh/OpenCASCADE**

Use millimetre CAD coordinates with nose axis `+X`, span axis `Y`, and up axis `+Z`. Create a cylindrical centre fuselage with a tapered nose, two swept trapezoidal main-wing solids, two smaller tailplane solids, and one vertical-tail solid. Keep parts as valid independent solids so STEP import remains stable and surfaces remain individually pickable.

- [ ] **Step 4: Run the geometry test**

Run the test from Step 2.

Expected: PASS and no invalid STEP import.

- [ ] **Step 5: Commit the fixture geometry**

```powershell
git add tests/e2e/test_public_workbench.py
git commit -m "test: use a reproducible fixed-wing UAV fixture"
```

### Task 2: Derive result fields from the same UAV surface

**Files:**
- Modify: `tests/e2e/test_public_workbench.py`

**Interfaces:**
- Consumes: `_public_synthetic_aircraft`, `GmshGeometryAdapter.build_surface_preview`, `pv.read`
- Produces: `_public_grid_result(source: Path, case_root: Path, target_cell_size_m: float)` with `surface_flow.vtu` matching the uploaded STEP bounds

- [ ] **Step 1: Add a failing same-geometry result test**

Add `test_public_result_surface_matches_uploaded_uav` that generates the UAV, calls `_public_grid_result`, reads `surface_flow.vtu`, and compares its bounds with `GmshGeometryAdapter.inspect_step(model).bounding_box` within 2 mm. Assert more than 100 surface cells and the presence of `Pressure_Coefficient`, `Pressure`, and `Y_Plus`.

- [ ] **Step 2: Run the new test and confirm the cube result fails**

```powershell
python -m pytest -q tests/e2e/test_public_workbench.py::test_public_result_surface_matches_uploaded_uav
```

Expected: FAIL because the current `pv.Cube` bounds do not match the STEP.

- [ ] **Step 3: Build deterministic fields on the production preview mesh**

Call `GmshGeometryAdapter.build_surface_preview(source, case_root / "public_uav_surface.vtk")`, read and triangulate the mesh with PyVista, and assign deterministic point fields based on normalized coordinates. Save the surface as `surface_flow.vtu`; retain the existing evidence wording that identifies it as a public synthetic test field.

- [ ] **Step 4: Update the browser runner to pass the uploaded source**

Change the default `_serve_public_app` runner so `_public_grid_result` receives `_source` as its first argument.

- [ ] **Step 5: Run both focused tests**

```powershell
python -m pytest -q tests/e2e/test_public_workbench.py -k "uav_proportions or result_surface_matches"
```

Expected: `2 passed`.

- [ ] **Step 6: Commit the same-surface result fixture**

```powershell
git add tests/e2e/test_public_workbench.py
git commit -m "test: render UAV result fields on the uploaded surface"
```

### Task 3: Regenerate and visually verify README evidence

**Files:**
- Modify: `artifacts/e2e/public_workbench_surface_selected.png`
- Modify: `artifacts/e2e/public_workbench_y_plus.png`
- Modify: `artifacts/e2e/browser_errors.json`

**Interfaces:**
- Consumes: `test_public_step_upload_renders_real_picker_and_toggles_surface`
- Produces: two headless-browser screenshots showing the same UAV in the picker and Y+ result

- [ ] **Step 1: Run the real browser workflow into the tracked artifact directory**

```powershell
$env:PAL_E2E_ARTIFACT_DIR = "artifacts/e2e"
python -m pytest -q tests/e2e/test_public_workbench.py::test_public_step_upload_renders_real_picker_and_toggles_surface
```

Expected: PASS, with `browser_errors.json` equal to `[]`.

- [ ] **Step 2: Inspect both screenshots**

Verify visually that both images show a recognizable fixed-wing UAV, the selected main-wing face is orange in the first image, and Y+ colors cover the UAV surface in the second.

- [ ] **Step 3: If picking misses the main wing, adjust only the deterministic click coordinate**

Use the rendered screenshot and canvas dimensions to choose a stable visible main-wing location; rerun Step 1 and confirm the selection count changes through the real picker API.

- [ ] **Step 4: Commit regenerated evidence**

```powershell
git add artifacts/e2e/public_workbench_surface_selected.png artifacts/e2e/public_workbench_y_plus.png artifacts/e2e/browser_errors.json tests/e2e/test_public_workbench.py
git commit -m "docs: show the public UAV in interface previews"
```

### Task 4: Regression, integration and publication

**Files:**
- Verify: repository working tree and public GitHub `main`

**Interfaces:**
- Consumes: all commits from Tasks 1–3
- Produces: a tested public `main` with accessible README image assets

- [ ] **Step 1: Run the full test suite**

```powershell
python -m pytest -q
```

Expected: exit code `0` with no failures.

- [ ] **Step 2: Verify repository hygiene and asset integrity**

```powershell
git diff --check
Get-FileHash artifacts/e2e/public_workbench_surface_selected.png, artifacts/e2e/public_workbench_y_plus.png -Algorithm SHA256
Get-Content artifacts/e2e/browser_errors.json
```

Expected: no whitespace errors; both hashes are recorded; browser errors are `[]`.

- [ ] **Step 3: Merge to `main`, rerun the full suite, and push**

Use a fast-forward merge from the isolated worktree branch, rerun `python -m pytest -q` on merged `main`, then push without changing the user's global Git proxy configuration.

- [ ] **Step 4: Verify the remote commit and both raw image URLs**

Confirm local `HEAD` equals `origin/main` and both `raw.githubusercontent.com` image requests return HTTP `200` with non-zero sizes.
