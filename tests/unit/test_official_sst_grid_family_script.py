from __future__ import annotations

import pytest

from scripts.run_official_sst_grid_family import (
    common_setup_fingerprint,
    official_asset_url,
    prepare_grid_config,
)


BASE_CONFIG = """\
SOLVER= RANS
KIND_TURB_MODEL= SST
SST_OPTIONS= V1994m
MACH_NUMBER= 0.15
AOA= 10.0
REYNOLDS_NUMBER= 6.0E6
RESTART_SOL= YES
ITER= 99999
MESH_FILENAME= n0012_225-65.su2
TABULAR_FORMAT= CSV
OUTPUT_WRT_FREQ= 10000
OUTPUT_FILES= (RESTART, PARAVIEW, SURFACE_PARAVIEW)
"""


def test_official_asset_url_is_pinned_to_su2code_release_repositories():
    assert official_asset_url(
        "SU2", "TestCases/rans/naca0012/turb_NACA0012_sst.cfg"
    ) == (
        "https://raw.githubusercontent.com/su2code/SU2/v8.5.0/"
        "TestCases/rans/naca0012/turb_NACA0012_sst.cfg"
    )
    assert official_asset_url(
        "TestCases", "rans/naca0012/n0012_113-33.su2"
    ).startswith("https://raw.githubusercontent.com/su2code/TestCases/v8.5.0/")

    for repository, path in (
        ("fork", "rans/naca0012/n0012_113-33.su2"),
        ("TestCases", "../private.step"),
        ("TestCases", "rans\\naca0012\\mesh.su2"),
    ):
        with pytest.raises(ValueError, match="OFFICIAL_ASSET_INVALID"):
            official_asset_url(repository, path)


def test_prepare_grid_config_only_changes_audited_runtime_controls():
    configured, changes = prepare_grid_config(
        BASE_CONFIG, mesh_filename="n0012_113-33.su2", iterations=3000
    )

    assert "RESTART_SOL= NO" in configured
    assert "ITER= 3000" in configured
    assert "MESH_FILENAME= n0012_113-33.su2" in configured
    assert "OUTPUT_WRT_FREQ= 100" in configured
    assert "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)" in configured
    assert "MACH_NUMBER= 0.15" in configured
    assert "AOA= 10.0" in configured
    assert "SST_OPTIONS= V1994m" in configured
    assert set(changes) == {
        "RESTART_SOL",
        "ITER",
        "MESH_FILENAME",
        "OUTPUT_WRT_FREQ",
        "HISTORY_OUTPUT",
    }


def test_common_setup_fingerprint_excludes_only_grid_identity():
    coarse, _ = prepare_grid_config(
        BASE_CONFIG, mesh_filename="n0012_113-33.su2", iterations=3000
    )
    fine, _ = prepare_grid_config(
        BASE_CONFIG, mesh_filename="n0012_449-129.su2", iterations=3000
    )

    assert common_setup_fingerprint(coarse) == common_setup_fingerprint(fine)
    assert common_setup_fingerprint(coarse) != common_setup_fingerprint(
        fine.replace("AOA= 10.0", "AOA= 9.0")
    )
