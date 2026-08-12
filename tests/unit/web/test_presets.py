from __future__ import annotations

import pytest

from phoenix_aero_lite.models.parameters import MeshMode
from phoenix_aero_lite.web.presets import analysis_presets, resolve_solver_preset


def test_catalog_exposes_five_user_workflows_with_scientific_limits():
    catalog = analysis_presets()

    assert tuple(catalog) == (
        "geometry_check",
        "trend",
        "standard",
        "grid_study",
        "custom",
    )
    assert catalog["geometry_check"].runs_solver is False
    assert catalog["trend"].evidence_ceiling == "diagnostic_only"
    assert catalog["standard"].boundary_layer == "enabled_and_audited"
    assert catalog["standard"].target_y_plus == pytest.approx(1.0)
    assert catalog["grid_study"].grid_levels == 3
    assert catalog["grid_study"].evidence_ceiling == "grid_sensitivity"
    assert catalog["custom"].allows_user_override is True
    assert all(item.purpose_zh and item.runtime_zh for item in catalog.values())


def test_solver_preset_maps_supported_modes_and_preserves_legacy_bookmarks():
    assert resolve_solver_preset("trend") == (MeshMode.PREVIEW, 300)
    assert resolve_solver_preset("standard") == (MeshMode.STANDARD, 800)
    assert resolve_solver_preset("custom", requested_iterations=123) == (
        MeshMode.STANDARD,
        123,
    )
    assert resolve_solver_preset("fast") == (MeshMode.PREVIEW, 300)
    assert resolve_solver_preset("fine") == (MeshMode.FINE, 1200)
    assert resolve_solver_preset("fast", requested_iterations=100) == (
        MeshMode.PREVIEW,
        100,
    )
    assert resolve_solver_preset("fine", requested_iterations=650) == (
        MeshMode.FINE,
        650,
    )


@pytest.mark.parametrize("name", ["geometry_check", "grid_study", "unknown"])
def test_non_single_solver_presets_cannot_be_misrepresented_as_one_case(name):
    with pytest.raises(ValueError, match="ANALYSIS_MODE_REQUIRES_SEPARATE_WORKFLOW"):
        resolve_solver_preset(name)
