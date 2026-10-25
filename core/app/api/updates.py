from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_app_state
from app.auth import require_admin
from app.services.server_release import ReleaseChecker
from app.state import AppState

router = APIRouter(prefix="/api/v1/updates", tags=["updates"])


class ServerReleaseOut(BaseModel):
    current: str
    latest: str | None
    update_available: bool
    url: str | None


@router.get("/server", response_model=ServerReleaseOut, dependencies=[Depends(require_admin)])
async def server_release(state: AppState = Depends(get_app_state)) -> ServerReleaseOut:
    """Whether a newer server version has been released (server mode; the
    desktop app with its own core updates itself)."""
    if state.settings.mode != "server":
        from app import __version__

        return ServerReleaseOut(current=__version__, latest=None, update_available=False, url=None)
    if state.release_checker is None:
        state.release_checker = ReleaseChecker(state.settings.release_repo)
    return ServerReleaseOut(**asdict(await state.release_checker.info()))
