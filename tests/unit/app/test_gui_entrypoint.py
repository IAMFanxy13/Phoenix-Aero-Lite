from phoenix_aero_lite.app import gui


def test_run_case_dispatch_does_not_construct_qapplication(monkeypatch):
    observed = {}

    def fake_run_case(argv):
        observed["argv"] = argv
        return 17

    monkeypatch.setattr("phoenix_aero_lite.cli.run_case", fake_run_case)
    monkeypatch.setattr(
        gui,
        "_start_desktop",
        lambda _argv: (_ for _ in ()).throw(AssertionError("desktop must not start")),
        raising=False,
    )

    assert gui.main(["PhoenixAeroLite.exe", "run-case", "--step", "air.step"]) == 17
    assert observed["argv"] == ["--step", "air.step"]


def test_frozen_launch_ignores_read_only_launcher_working_directory(tmp_path):
    project = tmp_path / "Phoenix_Aero_Lite"
    executable = project / "dist" / "PhoenixAeroLite" / "PhoenixAeroLite.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"frozen executable")
    (project / "config").mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='phoenix'\n")
    launcher_cwd = tmp_path / "Program Files" / "WindowsApps" / "OpenAI.Codex" / "app"
    launcher_cwd.mkdir(parents=True)

    resolved = gui._resolve_project_root(
        configured_root=None,
        executable_path=executable,
        cwd=launcher_cwd,
    )

    assert resolved == project.resolve()
