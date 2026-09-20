from __future__ import annotations

import time

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import AnimeRepo
from app.services import sorter
from app.services.jobs import EventBus

logger = structlog.get_logger(__name__)

# Ceiling on how stale the cached total may get. Everything that normally
# changes it publishes an event and invalidates the cache outright; this only
# covers the paths that don't -- most notably the scan adding episode files to
# an anime that already exists, which updates rows without announcing itself.
_CACHE_TTL_S = 60.0

_cached: tuple[float, int] | None = None


def invalidate() -> None:
    global _cached
    _cached = None


async def _on_event(payload: dict) -> None:
    event = payload.get("event")
    if isinstance(event, str) and event.startswith(("anime.", "folder.")):
        invalidate()


def register_invalidation(event_bus: EventBus) -> None:
    """Wires cache invalidation to the event bus. Call once at startup."""
    event_bus.subscribe(_on_event)


async def _compute_total(session: AsyncSession) -> int:
    anime_repo = AnimeRepo(session)
    return (
        await anime_repo.count_needing_review_or_manual()
        + await anime_repo.count_duplicate_groups()
        + await sorter.count_sort_queue(session)
        + await sorter.count_rename_queue(session)
    )


async def pending_actions_total(session: AsyncSession) -> int:
    """Everything waiting for a manual decision, across all queues.

    Cached in-process because the UI asks for this on every route and after
    every scan/identify event, while the answer only changes when the library
    does. Three of the four parts are SQL counts; the fourth (renaming) can't
    be -- whether a name matches depends on a title resolved from a user
    setting -- so it costs a pass over every episode row. Doing that pass once
    per actual change instead of once per request is the entire point of the
    cache. Single-process Core, so a module-level cache is the whole story;
    there's no second worker to keep coherent.
    """
    global _cached
    now = time.monotonic()
    if _cached is not None and now - _cached[0] < _CACHE_TTL_S:
        return _cached[1]

    started = time.monotonic()
    total = await _compute_total(session)
    _cached = (now, total)
    logger.debug("pending_actions_recomputed", total=total, took_ms=(time.monotonic() - started) * 1000)
    return total
