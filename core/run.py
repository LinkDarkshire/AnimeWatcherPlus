"""PyInstaller entry point for the core sidecar binary.

Mirrors `python -m uvicorn app.main:app --host ... --port ...` (the dev-mode
invocation in shell/src-tauri/src/lib.rs) so the Rust supervisor can pass the
same --host/--port args to either the dev venv's python or this frozen exe.
"""

from __future__ import annotations

import sys

import uvicorn

# Importing the app object directly (rather than passing the "app.main:app"
# string to uvicorn.run, which resolves it via a runtime importlib lookup)
# is required for PyInstaller: its static analyzer only bundles modules it
# can see imported somewhere -- a string it can't introspect means the whole
# `app` package silently never makes it into the frozen build.
from app.main import app as fastapi_app


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1
    uvicorn.run(fastapi_app, host=host, port=port)


if __name__ == "__main__":
    main()
