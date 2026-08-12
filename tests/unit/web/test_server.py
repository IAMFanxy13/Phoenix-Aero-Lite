import pytest

from phoenix_aero_lite.web import server


def test_default_launcher_binds_loopback_and_does_not_open_browser(tmp_path):
    observed = {}

    def run(app, **kwargs):
        observed.update(app=app, kwargs=kwargs)

    opened = []
    result = server.main(
        ["--project-root", str(tmp_path)],
        uvicorn_runner=run,
        browser_opener=opened.append,
        app_factory=lambda root: {"root": root},
    )

    assert result == 0
    assert observed["kwargs"]["host"] == "127.0.0.1"
    assert observed["kwargs"]["port"] == 8000
    assert opened == []


def test_launcher_rejects_non_loopback_host(tmp_path):
    with pytest.raises(SystemExit):
        server.main(
            ["--project-root", str(tmp_path), "--host", "0.0.0.0"],
            uvicorn_runner=lambda *_args, **_kwargs: None,
            app_factory=lambda root: root,
        )


def test_browser_opens_only_when_explicitly_requested(tmp_path):
    opened = []

    server.main(
        ["--project-root", str(tmp_path), "--port", "8123", "--open-browser"],
        uvicorn_runner=lambda *_args, **_kwargs: None,
        browser_opener=opened.append,
        app_factory=lambda root: root,
    )

    assert opened == ["http://127.0.0.1:8123"]
