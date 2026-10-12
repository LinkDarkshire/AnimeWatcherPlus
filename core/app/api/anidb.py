from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.providers.anidb import AniDBProvider
from app.providers.anidb_activity import anidb_status, waiting_counts
from app.state import AppState

router = APIRouter(prefix="/api/v1/anidb", tags=["anidb"])


class AniDBStatusOut(BaseModel):
    state: str  # idle | waiting | requesting
    detail: str | None
    wait_seconds: float | None
    requests_today: int
    daily_cap: int | None
    banned_until: float | None  # epoch seconds, only while a ban is active
    paused: bool  # circuit breaker open after repeated failures
    # Why no request can go out right now ("ban" | "daily_cap" | "paused")
    # and until when (epoch seconds).
    blocked_reason: str | None
    blocked_until: float | None
    # When the work that failed during a block was queued again.
    resumed_at: float | None
    queued_jobs: int
    waiting_anime: int
    waiting_wishlist: int


@router.get("/status", response_model=AniDBStatusOut)
async def get_anidb_status(
    state: AppState = Depends(get_app_state), session: AsyncSession = Depends(get_db)
) -> AniDBStatusOut:
    """What the core is doing with AniDB right now. The same snapshot is
    pushed live as the `anidb.activity` event on every change."""
    provider = state.provider_registry.get_provider("anidb")
    status = anidb_status(provider if isinstance(provider, AniDBProvider) else None, state.job_queue)
    status.update(await waiting_counts(session))
    return AniDBStatusOut(**status)
