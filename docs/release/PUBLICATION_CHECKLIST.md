# Publication checklist

## Use the clean export

- [ ] Open `PUBLIC_EXPORT_SANITIZATION.json`; confirm `sensitive_findings` is empty and `history_included` is false.
- [ ] Do not push the development repository or reuse its `.git` directory.
- [ ] Create a new empty GitHub repository under the intended owner.
- [ ] Copy only the history-free public export into a new local folder.
- [ ] Run the public test, lint, package and sensitive-scan commands again.
- [ ] Initialize a new Git repository, make one reviewed initial commit and add the new remote.

## GitHub settings

- [ ] Enable Issues and Discussions as desired.
- [ ] Enable Dependabot alerts, secret scanning, push protection and CodeQL.
- [ ] Create a branch ruleset requiring CI, Windows integration, CodeQL and review.
- [ ] Review CODEOWNERS, issue forms, support/security links and default branch name.
- [ ] Confirm that no Actions artifact contains private CAD, job data or local logs.

## Release decision

- [ ] Review the GPL-3.0-or-later choice and dependency matrix; obtain legal advice if commercial redistribution requires it.
- [ ] Publish source/wheel/sdist first if desired.
- [ ] Do not attach the internal PyInstaller directory until native license/NOTICE collection and clean-machine reproduction are complete.
- [ ] Create and sign the version tag manually.
- [ ] Review generated release notes and hashes before uploading.
- [ ] Do not upload to PyPI unless package ownership, versioning and support expectations are explicitly accepted.

## Suggested local commands

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
$env:PYVISTA_OFF_SCREEN = "true"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m build
```

No publication action is performed automatically by Phoenix Aero Lite.
