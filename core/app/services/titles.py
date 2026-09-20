from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Anime
from app.db.repositories import AnimeRepo
from app.db.session import session_scope
from app.domain.titles import (
    TITLE_VARIANT_EN,
    TITLE_VARIANT_JA,
    TITLE_VARIANT_MAIN,
    TitleEntry,
    Variants,
    pick_variants,
    resolve_title,
)
from app.providers.anidb import cached_title_variants
from app.services import artwork
from app.services.jobs import EventBus
from app.services.settings_store import get_display_title_order

logger = structlog.get_logger(__name__)


class TitledAnime(Protocol):
    """The title columns, and nothing else. Satisfied by the Anime model and
    by the flat column rows the queue listings select -- neither the resolver
    nor the rename planner needs a full ORM entity."""

    @property
    def title(self) -> str: ...
    @property
    def title_main(self) -> str | None: ...
    @property
    def title_en(self) -> str | None: ...
    @property
    def title_ja(self) -> str | None: ...


def variants_from_anime(anime: TitledAnime) -> Variants:
    return {
        TITLE_VARIANT_MAIN: anime.title_main,
        TITLE_VARIANT_EN: anime.title_en,
        TITLE_VARIANT_JA: anime.title_ja,
    }


def apply_variants(anime: Anime, variants: Variants) -> None:
    anime.title_main = variants.get(TITLE_VARIANT_MAIN)
    anime.title_en = variants.get(TITLE_VARIANT_EN)
    anime.title_ja = variants.get(TITLE_VARIANT_JA)


def load_variants_from_aniinfo(anime_dir: Path) -> Variants | None:
    """Recovers the title variants from the anime's own aniinfo.json sidecar.

    That file already carries AniDB's complete language-tagged title list and
    is written on every identification, so an existing library can be
    backfilled from local disk alone -- no AniDB request, and therefore no ban
    risk, for what is only a re-reading of data we already have.
    Returns None when the sidecar is missing, unreadable, or title-less.
    """
    try:
        raw = json.loads((anime_dir / artwork.ANIINFO_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    titles = raw.get("titles") if isinstance(raw, dict) else None
    if not isinstance(titles, list):
        return None
    entries: list[TitleEntry] = [
        (entry["value"], entry.get("language"), entry.get("type"))
        for entry in titles
        if isinstance(entry, dict) and isinstance(entry.get("value"), str)
    ]
    if not entries:
        return None
    return pick_variants(entries)


def has_known_variants(anime: TitledAnime) -> bool:
    """False for anime identified before the variant columns existed and not
    backfilled yet. Their `title` is a single untagged string from an older
    language cascade -- for many entries raw Japanese script -- so it must not
    be used to name anything on disk."""
    return any(variants_from_anime(anime).values())


def title_for(anime: TitledAnime, order: list[str]) -> str:
    """The name to use for this anime under `order` -- display or folder,
    depending on which of the two preference orders the caller passes in."""
    return resolve_title(variants_from_anime(anime), order, anime.title)


def _recover_variants(settings: Settings, anidb_id: int, anime_dir: Path) -> Variants | None:
    """Local AniDB response cache first (plain local file, no share access),
    then the aniinfo.json sidecar in the anime's own folder."""
    return cached_title_variants(settings, anidb_id) or load_variants_from_aniinfo(anime_dir)


async def resync_titles(session: AsyncSession, settings: Settings | None = None) -> int:
    """Re-derives every anime's stored display title from the current
    `display_title_order`, backfilling missing variants along the way. Returns
    the number of rows whose title actually changed.

    Runs as a startup job as well as after a title-order change: anime that
    the staleness rule excludes from rescans (`no_scan`) would otherwise keep
    their pre-variant title forever. The backfill never contacts AniDB.

    The resolved title is persisted rather than computed per request because
    the library list is ordered and full-text-searched by `anime.title` in
    SQL -- resolving at read time would leave the grid sorted by a string the
    user can no longer see.
    """
    settings = settings or get_settings()
    repo = AnimeRepo(session)
    order = await get_display_title_order(session)
    animes = list((await session.execute(select(Anime))).scalars().all())

    to_recover = [
        (anime.id, anime.anidb_id, Path(anime.directory_path))
        for anime in animes
        if anime.anidb_id is not None and not has_known_variants(anime)
    ]
    # File reads -- local cache, and sidecars on what is usually a network
    # share -- go to a worker thread in one batch rather than blocking the
    # event loop once per anime.
    recovered: dict[int, Variants | None] = {}
    if to_recover:
        recovered = await asyncio.to_thread(
            lambda: {aid: _recover_variants(settings, anidb_id, d) for aid, anidb_id, d in to_recover}
        )

    changed: list[Anime] = []
    # The FTS row indexes the variants too, so a backfill needs a re-sync even
    # when the resolved display title happens to stay the same.
    needs_fts: list[Anime] = []
    backfilled = 0
    for anime in animes:
        recovered_variants = recovered.get(anime.id)
        if recovered_variants is not None:
            apply_variants(anime, recovered_variants)
            backfilled += 1
        new_title = resolve_title(variants_from_anime(anime), order, anime.title)
        title_changed = new_title != anime.title
        if title_changed:
            anime.title = new_title
            changed.append(anime)
        if title_changed or recovered_variants is not None:
            needs_fts.append(anime)

    for anime in needs_fts:
        await repo.sync_fts(anime, commit=False)
    await session.commit()
    logger.info(
        "titles_resynced",
        checked=len(animes),
        backfilled=backfilled,
        unrecoverable=len(to_recover) - backfilled,
        changed=len(changed),
    )
    return len(changed)


async def run_startup_title_backfill(settings: Settings, event_bus: EventBus) -> None:
    """Startup job: brings every anime that still lacks title variants up to
    date. Costs one batch of local file reads the first time and next to
    nothing afterwards, since anime whose variants are known are skipped.

    Publishes an event when display titles changed, so an already-open UI
    refetches the library and the badge cache is dropped (its rename count
    depends on these titles too)."""
    async with session_scope() as session:
        changed = await resync_titles(session, settings)
    if changed:
        await event_bus.publish("anime.titles_resynced", {"changed": changed})
