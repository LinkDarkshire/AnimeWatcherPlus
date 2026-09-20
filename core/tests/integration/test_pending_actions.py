from __future__ import annotations

import pytest

from app.db.models import Anime
from app.db.repositories import AnimeRepo, FolderRepo
from app.services import pending_actions
from app.services.jobs import EventBus

pytestmark = pytest.mark.asyncio


async def _add_review_anime(session, folder_id: int, directory) -> Anime:
    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "needs_manual_id"
    await session.commit()
    return anime


async def test_total_is_cached_between_calls(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    assert await pending_actions.pending_actions_total(db_session) == 0

    await _add_review_anime(db_session, folder.id, tmp_path / "Show A")

    # Nothing announced the change, so the cached answer is still served --
    # this is the behavior that keeps the badge off the library on every
    # single request.
    assert await pending_actions.pending_actions_total(db_session) == 0


async def test_invalidate_forces_a_recount(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    assert await pending_actions.pending_actions_total(db_session) == 0

    await _add_review_anime(db_session, folder.id, tmp_path / "Show A")
    pending_actions.invalidate()

    assert await pending_actions.pending_actions_total(db_session) == 1


async def test_anime_events_invalidate_the_cache(db_session, tmp_path) -> None:
    """The production wiring: every anime.* / folder.* event drops the cache,
    so discovery, identification, sorting and removal all show up in the badge
    without the endpoint recounting on its own."""
    event_bus = EventBus()
    pending_actions.register_invalidation(event_bus)

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    assert await pending_actions.pending_actions_total(db_session) == 0

    await _add_review_anime(db_session, folder.id, tmp_path / "Show A")
    await event_bus.publish("anime.needs_review", {"anime_id": 1, "candidates": []})

    assert await pending_actions.pending_actions_total(db_session) == 1


async def test_unrelated_events_leave_the_cache_alone(db_session, tmp_path) -> None:
    event_bus = EventBus()
    pending_actions.register_invalidation(event_bus)

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    assert await pending_actions.pending_actions_total(db_session) == 0

    await _add_review_anime(db_session, folder.id, tmp_path / "Show A")
    await event_bus.publish("scan.progress", {"folder_id": folder.id})

    assert await pending_actions.pending_actions_total(db_session) == 0
