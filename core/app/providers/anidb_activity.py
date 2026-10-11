from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.providers.anidb import AniDBProvider
    from app.services.jobs import JobQueue

logger = structlog.get_logger(__name__)

ActivityState = Literal["idle", "waiting", "requesting"]
Listener = Callable[[], Awaitable[None]]

# Job types that may end up asking AniDB (cache hits don't, but whether one
# will is only known when the job runs).
ANIDB_JOB_TYPES = frozenset({"identify", "rescan", "wishlist_details", "titledump_import"})


# What the current task is fetching for ("Frieren"), so the activity display
# can name it instead of showing a bare AniDB id. Set by the callers
# (identification, wishlist), read by the provider.
_subject: ContextVar[str | None] = ContextVar("anidb_subject", default=None)


@contextmanager
def anidb_subject(label: str | None) -> Iterator[None]:
    token = _subject.set(label)
    try:
        yield
    finally:
        _subject.reset(token)


def describe(aid: int) -> str:
    label = _subject.get()
    return f"{label} (#{aid})" if label else f"Anime #{aid}"


class AniDBActivity:
    """What the app is doing with AniDB right now -- only real network
    requests, never answers from the local cache. Listeners are told about
    every change (the core pushes it to the UI as a live event)."""

    def __init__(self) -> None:
        self.state: ActivityState = "idle"
        self.detail: str | None = None  # "Anime #1234", "Titelliste"
        self.since: float | None = None
        self.wait_until: float | None = None
        # When work was put back in the queue after a ban/limit/pause ended.
        self.resumed_at: float | None = None
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    async def set(self, state: ActivityState, detail: str | None = None, wait_seconds: float | None = None) -> None:
        self.state = state
        self.detail = detail if state != "idle" else None
        self.since = time.time() if state != "idle" else None
        self.wait_until = time.time() + wait_seconds if wait_seconds else None
        await self.notify()

    async def notify(self) -> None:
        for listener in list(self._listeners):
            try:
                await listener()
            except Exception:  # a display hook must never break a request
                logger.exception("anidb_activity_listener_failed")


def anidb_status(provider: AniDBProvider | None, job_queue: JobQueue | None) -> dict[str, Any]:
    """Snapshot for the UI: current activity, today's request count against
    the daily cap, ban/circuit state and how many AniDB-bound jobs wait."""
    now = time.time()
    status: dict[str, Any] = {
        "state": "idle",
        "detail": None,
        "wait_seconds": None,
        "requests_today": 0,
        "daily_cap": None,
        "banned_until": None,
        "paused": False,
        "blocked_reason": None,
        "blocked_until": None,
        "resumed_at": None,
        "queued_jobs": job_queue.pending_count(ANIDB_JOB_TYPES) if job_queue is not None else 0,
        # Filled in by waiting_counts(): what still needs AniDB at all.
        "waiting_anime": 0,
        "waiting_wishlist": 0,
    }
    if provider is None:
        return status
    activity = provider.activity
    status.update(
        state=activity.state,
        detail=activity.detail,
        wait_seconds=max(0.0, round(activity.wait_until - now, 1)) if activity.wait_until else None,
        requests_today=provider.limiter.calls_today,
        daily_cap=provider.limiter.daily_cap,
        banned_until=provider.banned_until if provider.banned_until > now else None,
        paused=provider.circuit_breaker.is_open(),
        resumed_at=activity.resumed_at,
    )
    reason, until = provider.blocked()
    status.update(blocked_reason=reason, blocked_until=until)
    return status


async def waiting_counts(session: AsyncSession) -> dict[str, int]:
    """Anime still waiting for identification and wishlist entries without
    details -- the work that resumes once AniDB is reachable again."""
    from app.db.models import Anime, WishlistEntry

    anime = await session.scalar(select(func.count()).select_from(Anime).where(Anime.ident_status == "pending"))
    wishes = await session.scalar(
        select(func.count()).select_from(WishlistEntry).where(WishlistEntry.details_fetched_at.is_(None))
    )
    return {"waiting_anime": int(anime or 0), "waiting_wishlist": int(wishes or 0)}
