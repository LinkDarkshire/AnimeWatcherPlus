"""Entry point of the core: for the desktop app's sidecar (and its frozen
PyInstaller build) and for the standalone server (Docker).

Desktop (default): `run.py --host 127.0.0.1 --port 8000` -- what the desktop
shell starts, the same arguments in dev and frozen builds.

Server: `run.py --server` (or AWP_MODE=server) -- listens on the API port
and on the LAN-only pairing port (AWP_API_PORT / AWP_PAIRING_PORT, default
8784 / 8785), one process serving both.
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn

# Importing the app object directly (rather than passing the "app.main:app"
# string to uvicorn) is required for PyInstaller: it only bundles modules it
# can see imported.
from app.main import app as fastapi_app


def _arg(args: list[str], name: str, default: str) -> str:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


async def _serve_server_mode(host: str, api_port: int, pairing_port: int) -> None:
    # One app, two listeners. The app's lifespan (migrations, scanner, ...)
    # runs once, with the API listener; the middleware tells the two apart
    # by the port a request arrived on.
    api = uvicorn.Server(uvicorn.Config(fastapi_app, host=host, port=api_port, proxy_headers=True))
    pairing = uvicorn.Server(uvicorn.Config(fastapi_app, host=host, port=pairing_port, lifespan="off"))
    await asyncio.gather(api.serve(), pairing.serve())


def main() -> None:
    args = sys.argv[1:]
    if "--server" in args or os.environ.get("AWP_MODE") == "server":
        from app.config import get_settings

        settings = get_settings()
        if settings.mode != "server":
            sys.exit("--server needs AWP_MODE=server (the app reads its mode at import time)")
        asyncio.run(
            _serve_server_mode(_arg(args, "--host", "0.0.0.0"), settings.api_port, settings.pairing_port)
        )
        return
    uvicorn.run(fastapi_app, host=_arg(args, "--host", "127.0.0.1"), port=int(_arg(args, "--port", "8000")))


if __name__ == "__main__":
    main()
