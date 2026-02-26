from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import threading
import time
import webbrowser

import uvicorn


def _resolve_project_root() -> Path:
    env_root = os.environ.get("NORDHOLD_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = (
            exe_dir,
            exe_dir / "_internal",
            exe_dir.parent,
        )
        for candidate in candidates:
            if (candidate / "data" / "versions" / "index.json").exists():
                return candidate
        return exe_dir

    return Path(__file__).resolve().parents[2]


def _open_browser_delayed(url: str, delay_s: float = 1.0) -> None:
    time.sleep(max(0.0, delay_s))
    try:
        webbrowser.open(url)
    except Exception:
        # Browser open is best-effort. API should continue running even on failure.
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nordhold-realtime-launcher",
        description="Run Nordhold realtime API/UI server from source or bundled EXE.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    project_root = _resolve_project_root()
    web_dist = project_root / "web" / "dist"

    os.environ["NORDHOLD_PROJECT_ROOT"] = str(project_root)
    os.environ["NORDHOLD_WEB_DIST"] = str(web_dist)

    # Import after env setup so api.py resolves bundled paths correctly.
    from nordhold.api import app as api_app

    url = f"http://{args.host}:{args.port}"
    print(f"Nordhold project root: {project_root}")
    print(f"Web dist path: {web_dist}")
    if not web_dist.exists():
        print("Warning: web/dist is missing. UI root may return 503 until frontend bundle is available.")

    if not args.no_browser:
        threading.Thread(target=_open_browser_delayed, args=(url, 1.0), daemon=True).start()

    uvicorn.run(api_app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
