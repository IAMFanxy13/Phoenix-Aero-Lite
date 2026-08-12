from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_release_verifier_keeps_private_model_checks_explicit_and_optional():
    script = (ROOT / "scripts" / "verify_release.ps1").read_text(encoding="utf-8")

    assert "[string]$ProtectedStep" in script
    assert "[string]$ProtectedSolidWorks" in script
    assert "PRIVATE_SOURCE_CHECK_NOT_REQUESTED" in script
    assert 'Join-Path $ModelRoot "example_model.STEP"' not in script
    assert 'Join-Path $ModelRoot "example_model.SLDPRT"' not in script


def test_source_launcher_is_loopback_first_and_has_noninteractive_check():
    script = (ROOT / "scripts" / "start_phoenix_aero_lite.ps1").read_text(
        encoding="utf-8"
    )

    assert "[switch]$NoBrowser" in script
    assert "[switch]$CheckOnly" in script
    assert 'http://127.0.0.1:$Port/' in script
    assert "Get-NetTCPConnection" in script
    assert "-WindowStyle Hidden" in script
    assert "$Backend.WaitForExit()" in script
    assert "$Backend.Refresh()" in script
    assert "if ($BackendExitCode -ne 0)" in script
    assert "WEB_BACKEND_RUNTIME_FAILED" in script


def test_double_click_launcher_enables_utf8_before_chinese_diagnostics():
    path = ROOT / "Start_Phoenix_Aero_Lite.cmd"
    script = path.read_text(encoding="utf-8")
    content = path.read_bytes()

    assert "chcp 65001 >nul" in script
    assert "Phoenix Aero Lite 未能启动" in script
    assert "exit /b %PAL_EXIT_CODE%" in script
    assert b"\r\n" in content
    assert content.replace(b"\r\n", b"").find(b"\n") == -1


def test_windows_bundle_excludes_development_only_typecheck_and_test_runtimes():
    spec = (ROOT / "packaging" / "phoenix_aero_lite.spec").read_text(
        encoding="utf-8"
    )

    assert '"mypy"' in spec
    assert '"pytest"' in spec
    assert '"py"' in spec


def test_github_ci_uses_the_official_pyvista_headless_display_action():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    unit = (ROOT / ".github" / "workflows" / "unit-tests.yml").read_text(
        encoding="utf-8"
    )

    assert ci.count("uses: pyvista/setup-headless-display-action@v3") == 2
    assert unit.count("uses: pyvista/setup-headless-display-action@v3") == 1
    assert ci.count("qt: true") == 2
    assert unit.count("qt: true") == 1


def test_github_ci_installs_the_gmsh_glu_runtime_on_linux():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "sudo apt-get install -y libglu1-mesa" in ci


def test_github_ci_diff_guard_only_rejects_tracked_file_changes():
    workflows = [
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in ("ci.yml", "unit-tests.yml")
    ]

    for workflow in workflows:
        assert "git diff --exit-code" in workflow
        assert "git diff --cached --exit-code" in workflow
        assert "git status --porcelain" not in workflow
