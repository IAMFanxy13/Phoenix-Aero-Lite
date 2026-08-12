import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from scripts.export_public_release import (
    export_public_release,
    find_sensitive_text,
    is_public_release_excluded,
    sanitize_public_text,
)


def _git(source: Path, *arguments: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=source,
        input=input_text,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _tracked_repository(tmp_path: Path, files: dict[str, bytes]) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet")
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _git(source, "add", ".")
    _git(
        source,
        "-c",
        "user.name=Phoenix Test",
        "-c",
        "user.email=phoenix.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    return source


def test_public_export_excludes_private_and_runtime_only_inputs():
    excluded = (
        "tests/local/test_air_step_pipeline.py",
        "tests/fixtures/su2/air_step_real_history.csv",
        "tests/unit/solver/test_air_step_regression.py",
        "docs/research/environment_inventory.md",
        "docs/research/su2_windows_installation.md",
        "artifacts/upstream_validation/run/stdout.txt",
        "web-data/jobs/job.json",
        "config/local_tools.json",
    )

    assert all(is_public_release_excluded(path) for path in excluded)
    assert not is_public_release_excluded("src/phoenix_aero_lite/web/app.py")
    assert not is_public_release_excluded(
        "artifacts/e2e/public_workbench_y_plus.png"
    )


def test_public_text_sanitizer_removes_private_model_names_without_hiding_status():
    private_step = "Air" + ".STEP"
    private_cad = "Air" + ".SLDPRT"
    text = (
        f"{private_step} remained stagnated; {private_cad} was not modified. "
        "The result is diagnostic-only."
    )

    sanitized = sanitize_public_text(text)

    assert private_step not in sanitized
    assert private_cad not in sanitized
    assert "example_model.STEP" in sanitized
    assert "example_model.SLDPRT" in sanitized
    assert "stagnated" in sanitized
    assert find_sensitive_text(sanitized) == ()


def test_sensitive_scan_detects_local_identity_credentials_and_private_hashes():
    private_hash = "A" * 64
    findings = find_sensitive_text(
        "C:" + "\\Users\\" + "example-user\\private "
        + "ghp_" + "1" * 36 + " " + private_hash,
        private_hashes=(private_hash,),
    )

    assert set(findings) == {
        "LOCAL_WINDOWS_PATH",
        "GITHUB_TOKEN",
        "PRIVATE_MODEL_HASH",
    }


def test_private_hash_scan_is_opt_in():
    private_hash = "B" * 64

    assert find_sensitive_text(private_hash) == ()
    assert find_sensitive_text(private_hash, private_hashes=(private_hash,)) == (
        "PRIVATE_MODEL_HASH",
    )


def test_public_export_rejects_a_tracked_binary_by_actual_sha256(tmp_path: Path):
    private = b"private CAD bytes\x00that cannot be decoded as release text"
    source = _tracked_repository(tmp_path, {"private.bin": private})
    denied = hashlib.sha256(private).hexdigest()
    destination = tmp_path / "public"

    with pytest.raises(ValueError, match="PUBLIC_EXPORT_PRIVATE_HASH_DENIED"):
        export_public_release(source, destination, private_hashes=(denied,))

    assert not destination.exists()


@pytest.mark.parametrize("invalid_hash", ("", "0" * 63, "G" * 64))
def test_public_export_rejects_invalid_private_hash_input(
    tmp_path: Path,
    invalid_hash: str,
):
    source = _tracked_repository(tmp_path, {"README.md": b"public"})

    with pytest.raises(ValueError, match="PUBLIC_EXPORT_PRIVATE_HASH_INVALID"):
        export_public_release(
            source,
            tmp_path / "public",
            private_hashes=(invalid_hash,),
        )


def test_public_export_rejects_git_symlink_entries_even_on_windows(tmp_path: Path):
    source = _tracked_repository(tmp_path, {"target.bin": b"private target"})
    link_blob = _git(source, "hash-object", "-w", "--stdin", input_text="target.bin")
    _git(source, "update-index", "--add", "--cacheinfo", "120000", link_blob, "linked.bin")
    _git(
        source,
        "-c",
        "user.name=Phoenix Test",
        "-c",
        "user.email=phoenix.invalid",
        "commit",
        "--quiet",
        "-m",
        "tracked symlink",
    )
    # With core.symlinks=false Git represents the link as an ordinary text file,
    # so the exporter must inspect the tracked mode instead of trusting Path.
    (source / "linked.bin").write_text("target.bin", encoding="utf-8")

    with pytest.raises(ValueError, match="PUBLIC_EXPORT_UNSAFE_SOURCE_PATH"):
        export_public_release(source, tmp_path / "public")


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe acceptance")
def test_public_export_normalizes_cmd_and_propagates_launcher_failure(tmp_path: Path):
    project_root = Path(__file__).parents[2]
    source = _tracked_repository(
        tmp_path,
        {
            "Start_Phoenix_Aero_Lite.cmd": (
                project_root / "Start_Phoenix_Aero_Lite.cmd"
            ).read_bytes(),
            "scripts/start_phoenix_aero_lite.ps1": (
                project_root / "scripts" / "start_phoenix_aero_lite.ps1"
            ).read_bytes(),
        },
    )
    destination = tmp_path / "public"

    export_public_release(source, destination)

    launcher = destination / "Start_Phoenix_Aero_Lite.cmd"
    content = launcher.read_bytes()
    assert b"\r\n" in content
    assert content.replace(b"\r\n", b"").find(b"\n") == -1
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher), "-CheckOnly", "-NoBrowser"],
        cwd=destination,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 11
    assert b"not recognized" not in completed.stdout
