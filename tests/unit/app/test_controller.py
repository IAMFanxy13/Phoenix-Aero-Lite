from importlib import metadata
from pathlib import Path

from phoenix_aero_lite.app import controller


def test_package_version_falls_back_to_imported_module_in_frozen_build(monkeypatch):
    class PackagedModule:
        __version__ = "4.15.2"

    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(controller.metadata, "version", missing_distribution)
    monkeypatch.setattr(
        controller.importlib,
        "import_module",
        lambda _name: PackagedModule,
    )

    assert controller._package_version("gmsh") == "4.15.2"


def test_each_gui_mesh_attempt_gets_a_new_unpublished_directory(tmp_path: Path):
    first = controller._new_gui_mesh_output_directory(tmp_path / "case-001")
    second = controller._new_gui_mesh_output_directory(tmp_path / "case-001")

    assert first != second
    assert first.parent == tmp_path / "case-001" / "gui_mesh_runs"
    assert second.parent == first.parent
    assert not first.exists()
    assert not second.exists()


def test_worker_error_text_preserves_the_root_cause():
    try:
        try:
            raise PermissionError("old mesh directory is busy")
        except PermissionError as cause:
            raise RuntimeError("MESH_ARTIFACT_WRITE_FAILED") from cause
    except RuntimeError as error:
        message = controller._format_error_chain(error)

    assert message == (
        "RuntimeError: MESH_ARTIFACT_WRITE_FAILED <- "
        "PermissionError: old mesh directory is busy"
    )
