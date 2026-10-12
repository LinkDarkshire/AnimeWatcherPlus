from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import partial

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnidbTitleEntry, Anime, WishlistEntry
from app.db.session import session_scope
from app.domain.titles import pick_variants, resolve_title, variants_from_metadata
from app.providers.anidb_activity import anidb_subject
from app.providers.base import ProviderRegistry
from app.services.jobs import EventBus, JobQueue
from app.services.settings_store import get_display_title_order
from app.services.titledump import fuzzy_match

logger = structlog.get_logger(__name__)


class WishlistConflict(Exception):
    """The anime is already on the wishlist or already in the library."""


class UnknownAnime(Exception):
    """The AniDB ID isn't in the local title dump."""


@dataclass
class WishlistCandidate:
    anidb_id: int
    title: str
    matched_title: str
    score: float
    in_library: bool
    on_wishlist: bool


@dataclass
class WishlistItem:
    id: int
    anidb_id: int
    title: str
    year: int | None
    media_type: str | None
    episode_count: int | None
    details_pending: bool
    library_anime_id: int | None
    created_at: dt.datetime


async def _display_titles(session: AsyncSession, anidb_ids: list[int]) -> dict[int, str]:
    """Each anime's name under the user's display order, from the local
    title dump -- the fuzzy match only says *which* title matched the query,
    which may well be an obscure synonym."""
    if not anidb_ids:
        return {}
    rows = (
        await session.execute(
            select(AnidbTitleEntry.aid, AnidbTitleEntry.title, AnidbTitleEntry.lang, AnidbTitleEntry.title_type)
            .where(AnidbTitleEntry.aid.in_(anidb_ids))
            .order_by(AnidbTitleEntry.id)
        )
    ).all()
    by_aid: dict[int, list[tuple[str, str | None, str | None]]] = {}
    for aid, title, lang, title_type in rows:
        by_aid.setdefault(aid, []).append((title, lang, title_type))
    order = await get_display_title_order(session)
    return {
        aid: resolve_title(pick_variants(entries), order, entries[0][0]) for aid, entries in by_aid.items()
    }


async def _library_anime_ids(session: AsyncSession, anidb_ids: list[int]) -> dict[int, int]:
    """AniDB ID -> id of an anime in the library with that ID (lowest id, so
    a duplicate group links to its primary entry)."""
    if not anidb_ids:
        return {}
    rows = (
        await session.execute(
            select(Anime.anidb_id, Anime.id).where(Anime.anidb_id.in_(anidb_ids)).order_by(Anime.id)
        )
    ).all()
    found: dict[int, int] = {}
    for anidb_id, anime_id in rows:
        if anidb_id is not None:
            found.setdefault(anidb_id, anime_id)
    return found


async def search(session: AsyncSession, query: str, limit: int = 10) -> list[WishlistCandidate]:
    """Searches the local AniDB title dump -- AniDB's HTTP API has no title
    search, and the dump is what identification uses too, so this costs no
    request and carries no ban risk. A plain number is taken as an AniDB ID."""
    query = query.strip()
    if not query:
        return []

    if query.isdigit():
        aid = int(query)
        titles = await _display_titles(session, [aid])
        matches = [(aid, titles[aid], 100.0)] if aid in titles else []
    else:
        matches = [(c.aid, c.title, c.score) for c in await fuzzy_match(session, query, limit=limit)]
    if not matches:
        return []

    ids = [aid for aid, _, _ in matches]
    titles = await _display_titles(session, ids)
    in_library = await _library_anime_ids(session, ids)
    wished = set(
        (await session.execute(select(WishlistEntry.anidb_id).where(WishlistEntry.anidb_id.in_(ids)))).scalars()
    )
    return [
        WishlistCandidate(
            anidb_id=aid,
            title=titles.get(aid, matched),
            matched_title=matched,
            score=score,
            in_library=aid in in_library,
            on_wishlist=aid in wished,
        )
        for aid, matched, score in matches
    ]


async def add(session: AsyncSession, anidb_id: int) -> WishlistEntry:
    if await session.scalar(select(WishlistEntry.id).where(WishlistEntry.anidb_id == anidb_id)) is not None:
        raise WishlistConflict("Anime steht bereits auf der Wunschliste")
    if await session.scalar(select(Anime.id).where(Anime.anidb_id == anidb_id).limit(1)) is not None:
        raise WishlistConflict("Anime ist bereits in der Bibliothek")
    titles = await _display_titles(session, [anidb_id])
    if anidb_id not in titles:
        raise UnknownAnime(f"AniDB-ID {anidb_id} ist unbekannt")

    entry = WishlistEntry(anidb_id=anidb_id, title=titles[anidb_id])
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def remove(session: AsyncSession, entry_id: int) -> bool:
    entry = await session.get(WishlistEntry, entry_id)
    if entry is None:
        return False
    await session.delete(entry)
    await session.commit()
    return True


async def list_items(session: AsyncSession) -> list[WishlistItem]:
    entries = list(
        (await session.execute(select(WishlistEntry).order_by(WishlistEntry.title.collate("NOCASE")))).scalars()
    )
    in_library = await _library_anime_ids(session, [e.anidb_id for e in entries])
    return [
        WishlistItem(
            id=e.id,
            anidb_id=e.anidb_id,
            title=e.title,
            year=e.year,
            media_type=e.media_type,
            episode_count=e.episode_count,
            details_pending=e.details_fetched_at is None,
            library_anime_id=in_library.get(e.anidb_id),
            created_at=e.created_at,
        )
        for e in entries
    ]


async def fetch_details(entry_id: int, provider_registry: ProviderRegistry, event_bus: EventBus) -> None:
    """Background job: year, type and episode count from AniDB, so entries
    with the same title (a remake and its original) can be told apart. Goes
    through the provider chain, i.e. the same rate limiter, response cache
    and ban handling as identification. Nothing is lost if it fails -- the
    entry simply keeps showing its title only."""
    async with session_scope() as session:
        entry = await session.get(WishlistEntry, entry_id)
        if entry is None:
            return
        anidb_id = entry.anidb_id
        title = entry.title

    with anidb_subject(f"Wunschliste: {title}"):
        metadata, _ = await provider_registry.fetch_chain({"anidb": str(anidb_id)})
    if metadata is None:
        logger.info("wishlist_details_unavailable", anidb_id=anidb_id)
        return

    async with session_scope() as session:
        entry = await session.get(WishlistEntry, entry_id)
        if entry is None:  # removed while the request was running
            return
        order = await get_display_title_order(session)
        entry.title = resolve_title(variants_from_metadata(metadata), order, entry.title)
        entry.year = metadata.year
        entry.media_type = metadata.media_type
        # Regular episodes only: specials/credits/trailers (S1, C1, T1) would
        # inflate the count the same way they're kept out of completeness.
        entry.episode_count = sum(1 for e in metadata.episodes if e.ep_number.isdigit()) or None
        entry.details_fetched_at = dt.datetime.now(dt.UTC)
        await session.commit()

    await event_bus.publish("wishlist.updated", {"entry_id": entry_id})


async def enqueue_pending_details(job_queue: JobQueue, provider_registry: ProviderRegistry, event_bus: EventBus) -> int:
    """Re-queues the details fetch for every entry that doesn't have them
    yet (it failed during an AniDB ban/limit)."""
    async with session_scope() as session:
        ids = list(
            (await session.execute(select(WishlistEntry.id).where(WishlistEntry.details_fetched_at.is_(None)))).scalars()
        )
    for entry_id in ids:
        job_queue.enqueue("wishlist_details", partial(fetch_details, entry_id, provider_registry, event_bus))
    return len(ids)
