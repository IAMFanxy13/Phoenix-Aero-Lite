"""Safe loopback launcher for the local Phoenix Aero Lite web app."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import webbrowser
from typing import Callable

import uvicorn

from phoenix_aero_lite.utilities.project_root import resolve_project_root
from phoenix_aero_lite.web.app import create_app


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main(
    argv: list[str] | None = None,
    *,
    uvicorn_runner: Callable[..., object] = uvicorn.run,
    browser_opener: Callable[[str], object] = webbrowser.open,
    app_factory: Callable[[Path], object] = create_app,
) -> int:
    parser = argparse.ArgumentParser(prog="phoenix-aero-lite-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in _LOOPBACK_HOSTS:
        parser.error("WEB_HOST_MUST_BE_LOOPBACK")
    if not 1 <= args.port <= 65535:
        parser.error("WEB_PORT_INVALID")
    project_root = resolve_project_root(
        configured_root=(
            str(args.project_root)
            if args.project_root is not None
            else os.environ.get("PAL_PROJECT_ROOT")
        ),
        executable_path=Path(sys.executable),
        cwd=Path.cwd(),
    )
    app = app_factory(project_root)
    url = f"http://{args.host}:{args.port}"
    if args.open_browser:
        browser_opener(url)
    uvicorn_runner(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
