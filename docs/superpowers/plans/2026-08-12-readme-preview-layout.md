# README Preview Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two existing README interface previews readable and visually cleaner without changing their content.

**Architecture:** Replace the two-column Markdown table with two full-width, vertically stacked figures. Keep the existing image assets and scientific disclaimer unchanged so the preview remains truthful and reviewable.

**Tech Stack:** GitHub Flavored Markdown, HTML image tags, Git.

## Global Constraints

- Modify only the README interface-preview layout and its two existing image references.
- Do not edit or replace either screenshot asset.
- Keep the existing screenshot disclaimer unchanged.
- Do not modify product source code.

---

### Task 1: Full-width interface previews

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `artifacts/e2e/public_workbench_surface_selected.png` and `artifacts/e2e/public_workbench_y_plus.png`
- Produces: a GitHub-renderable README section with two full-width stacked previews

- [ ] **Step 1: Capture the current section as the failing layout check**

Run:

```powershell
Select-String -Path README.md -Pattern '^\| 主翼表面真实点选 \| 求解后壁面 Y\+ \|$'
```

Expected: one match, proving the unwanted two-column table is present.

- [ ] **Step 2: Replace the table with stacked full-width figures**

Use this exact structure:

```markdown
### 👆 主翼表面真实点选

<p align="center">
  <img src="artifacts/e2e/public_workbench_surface_selected.png" alt="主翼表面真实点选界面" width="100%">
</p>

### 🌈 求解后壁面 Y+

<p align="center">
  <img src="artifacts/e2e/public_workbench_y_plus.png" alt="求解后壁面 Y+ 界面" width="100%">
</p>
```

- [ ] **Step 3: Verify scope, image references, and removal of the table**

Run:

```powershell
git diff --check
git diff -- README.md
Select-String -Path README.md -Pattern 'public_workbench_surface_selected.png|public_workbench_y_plus.png'
```

Expected: no whitespace errors; only the preview block changes; both image paths occur once.

- [ ] **Step 4: Verify both referenced image files exist and are non-empty**

Run:

```powershell
Get-Item artifacts/e2e/public_workbench_surface_selected.png, artifacts/e2e/public_workbench_y_plus.png |
  Select-Object FullName, Length
```

Expected: both paths exist and each `Length` is greater than zero.

- [ ] **Step 5: Commit and publish**

```powershell
git add README.md docs/superpowers/plans/2026-08-12-readme-preview-layout.md
git commit -m "docs: improve interface preview layout"
git push origin main
```

Expected: push succeeds and `main` matches `origin/main`.
