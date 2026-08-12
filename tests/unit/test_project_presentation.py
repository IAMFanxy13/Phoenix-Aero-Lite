from __future__ import annotations

from pathlib import Path
import re
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_URL = "https://github.com/IAMFanxy13/Phoenix-Aero-Lite"
CURRENT_GITHUB_HANDLE = "IAMFanxy13"
OBSOLETE_GITHUB_HANDLE = "Fan" + "-Xinyu"


def test_public_package_metadata_targets_the_current_repository() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert metadata["authors"] == [{"name": "Xinyu Fan"}]
    assert metadata["urls"] == {
        "Documentation": f"{REPOSITORY_URL}#readme",
        "Issues": f"{REPOSITORY_URL}/issues",
        "Source": REPOSITORY_URL,
    }


def test_public_readmes_are_utf8_and_reference_real_landing_assets() -> None:
    primary = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    english = (PROJECT_ROOT / "README.en.md").read_text(encoding="utf-8")
    chinese_alias = (PROJECT_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    combined = "\n".join((primary, english, chinese_alias))

    assert primary.startswith("# 🚀 Phoenix Aero Lite")
    assert "English" in primary and "README.en.md" in primary
    assert "Alpha" in primary
    assert "Gmsh" in primary and "SU2" in primary and "PyVista" in primary
    assert "复用" in primary
    assert "artifacts/e2e/public_workbench_surface_selected.png" in primary
    assert "artifacts/e2e/public_workbench_y_plus.png" in primary
    assert "img.shields.io" in primary
    assert "README.md" in chinese_alias
    assert all(marker not in combined for marker in ("鏄", "涓", "鍚", "鈥", "�"))

    image_targets = re.findall(r"!\[[^]]*]\(([^)]+)\)", primary)
    assert image_targets
    for target in image_targets:
        if target.startswith(("http://", "https://")):
            continue
        assert (PROJECT_ROOT / target).is_file(), target


def test_public_presentation_and_github_routing_use_only_current_account() -> None:
    presentation_paths = [
        PROJECT_ROOT / "CITATION.cff",
        PROJECT_ROOT / "pyproject.toml",
        *PROJECT_ROOT.glob("README*.md"),
        *(path for path in (PROJECT_ROOT / ".github").rglob("*") if path.is_file()),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in presentation_paths)

    assert OBSOLETE_GITHUB_HANDLE not in combined
    assert f"@{CURRENT_GITHUB_HANDLE}" in combined
    assert REPOSITORY_URL in combined


def test_citation_matches_the_public_snapshot_date() -> None:
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")

    assert 'date-released: "2026-08-12"' in citation
