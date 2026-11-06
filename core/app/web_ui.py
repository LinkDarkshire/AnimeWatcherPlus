"""The web interface (server mode): the same UI as the apps, built into the
server image and served from the API port. Everything that isn't an API
route gets the page; the UI's router takes it from there."""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

logger = structlog.get_logger(__name__)

# The page loads nothing from elsewhere; posters may come from AniDB's
# image servers.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; connect-src 'self'; font-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)
_NOT_THE_PAGE = ("api/", "ws", "pair", "admin", "health")


class _HashedAssets(StaticFiles):
    """Built files with a content hash in their name never change."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response


def mount(app: FastAPI, folder: Path) -> None:
    root = folder.resolve()
    index = root / "index.html"
    if not index.is_file():
        logger.warning("web_ui_missing", folder=str(folder))
        return
    if (root / "assets").is_dir():
        app.mount("/assets", _HashedAssets(directory=root / "assets"), name="web-ui-assets")
    page_headers = {"content-security-policy": CONTENT_SECURITY_POLICY}

    @app.get("/{path:path}", include_in_schema=False)
    async def page(path: str) -> FileResponse:
        if path.startswith(_NOT_THE_PAGE):
            raise HTTPException(status_code=404, detail="Not Found")
        # Files next to the page (favicon); anything else is a UI route.
        if path:
            candidate = (root / path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(index, headers=page_headers)

    logger.info("web_ui_enabled", folder=str(folder))
