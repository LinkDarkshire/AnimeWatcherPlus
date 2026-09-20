from __future__ import annotations

import asyncio
import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Anime, ExpectedEpisode, LocalEpisode
from app.db.repositories import AnimeRepo
from app.domain.metadata import AnimeMetadata
from app.domain.titles import TITLE_VARIANT_EN, TITLE_VARIANT_JA, TITLE_VARIANT_MAIN, resolve_title
from app.providers import anidb
from app.services import artwork
from app.services.episode_parse import guess_episode_number
from app.services.jobs import EventBus
from app.services.settings_store import get_display_title_order
from app.services.titles import (
    apply_variants,
    has_known_variants,
    load_variants_from_aniinfo,
    variants_from_anime,
)

logger = structlog.get_logger(__name__)


@dataclass
class RepairReport:
    """What one repair pass actually changed, so the UI can report more than
    just "done"."""

    checked: int = 0
    titles_backfilled: int = 0
    titles_changed: int = 0
    episode_numbers_fixed: int = 0
    metadata_filled: int = 0
    expected_episodes_added: int = 0
    posters_relinked: int = 0
    without_local_source: int = 0


@dataclass
class _LocalSource:
    """Everything a repair pass can learn about one anime without going to
    the network."""

    metadata: AnimeMetadata | None = None
    variants: dict[str, str | None] | None = None
    poster_on_disk: bool = False


def _read_local_source(
    settings: Settings, anidb_id: int, anime_dir: Path, needs_poster: bool
) -> _LocalSource:
    source = _LocalSource()
    source.metadata = anidb.cached_metadata(settings, anidb_id)
    if source.metadata is None:
        # No cached AniDB response for this anime -- its own sidecar still
        # carries the title list, which is the most valuable part.
        source.variants = load_variants_from_aniinfo(anime_dir)
    if needs_poster:
        try:
            source.poster_on_disk = (anime_dir / artwork.POSTER_FILENAME).is_file()
        except OSError:
            source.poster_on_disk = False
    return source


async def run_repair_scan(
    session: AsyncSession, settings: Settings, event_bus: EventBus | None = None
) -> RepairReport:
    """Re-derives everything the app can work out from data it already holds
    locally, for *every* anime -- explicitly including those the staleness
    rule has frozen out of normal rescans (`no_scan`).

    Deliberately never contacts AniDB: it repairs from the on-disk response
    cache, the aniinfo.json sidecars and the filenames themselves. That makes
    it safe to run at any time, unlike the full rescan, which re-fetches the
    whole library and carries a real ban risk.

    It fills gaps rather than overwriting: an existing year/type/description
    is left alone. Purely derived values -- the display title, and the episode
    number parsed from a filename -- are always recomputed, since correcting
    those is the point.
    """
    repo = AnimeRepo(session)
    report = RepairReport()

    animes = list((await session.execute(select(Anime))).scalars().all())
    report.checked = len(animes)
    have_episodes = {
        anime_id
        for (anime_id,) in await session.execute(
            select(ExpectedEpisode.anime_id).group_by(ExpectedEpisode.anime_id)
        )
    }

    candidates = [(a.id, a.anidb_id, Path(a.directory_path), a.poster_path is None)
                  for a in animes if a.anidb_id is not None]
    # One batch of file reads in a worker thread: the AniDB cache is local,
    # but sidecars and posters usually sit on a network share.
    sources: dict[int, _LocalSource] = {}
    if candidates:
        sources = await asyncio.to_thread(
            lambda: {
                anime_id: _read_local_source(settings, anidb_id, directory, needs_poster)
                for anime_id, anidb_id, directory, needs_poster in candidates
            }
        )

    order = await get_display_title_order(session)
    needs_fts: list[Anime] = []

    for anime in animes:
        source = sources.get(anime.id, _LocalSource())
        changed_row = False

        if not has_known_variants(anime):
            variants = _variants_from_source(source)
            if variants is not None:
                apply_variants(anime, variants)
                report.titles_backfilled += 1
                changed_row = True
            elif anime.anidb_id is not None:
                report.without_local_source += 1

        if source.metadata is not None:
            if _fill_missing_metadata(anime, source.metadata):
                report.metadata_filled += 1
                changed_row = True
            if anime.id not in have_episodes and source.metadata.episodes:
                _add_expected_episodes(session, anime, source.metadata)
                report.expected_episodes_added += 1
                changed_row = True

        if anime.poster_path is None and source.poster_on_disk:
            # The artwork is there, only the pointer to it was lost.
            anime.poster_path = artwork.POSTER_FILENAME
            report.posters_relinked += 1
            changed_row = True

        new_title = resolve_title(variants_from_anime(anime), order, anime.title)
        if new_title != anime.title:
            anime.title = new_title
            report.titles_changed += 1
            changed_row = True

        if changed_row:
            needs_fts.append(anime)

    report.episode_numbers_fixed = await _reparse_episode_numbers(session)

    for anime in needs_fts:
        await repo.sync_fts(anime, commit=False)
    await session.commit()

    logger.info("repair_scan_finished", **vars(report))
    if event_bus is not None:
        await event_bus.publish("library.repaired", vars(report))
    return report


def _variants_from_source(source: _LocalSource) -> dict[str, str | None] | None:
    if source.metadata is not None:
        variants = {
            TITLE_VARIANT_MAIN: source.metadata.title_main,
            TITLE_VARIANT_EN: source.metadata.title_en,
            TITLE_VARIANT_JA: source.metadata.title_ja,
        }
        if any(variants.values()):
            return variants
    return source.variants


def _fill_missing_metadata(anime: Anime, metadata: AnimeMetadata) -> bool:
    filled = False
    for attribute, value in (
        ("year", metadata.year),
        ("media_type", metadata.media_type),
        ("description", metadata.description),
        ("original_title", metadata.original_title),
    ):
        if getattr(anime, attribute) is None and value is not None:
            setattr(anime, attribute, value)
            filled = True
    return filled


def _add_expected_episodes(session: AsyncSession, anime: Anime, metadata: AnimeMetadata) -> None:
    for episode in metadata.episodes:
        session.add(
            ExpectedEpisode(
                anime_id=anime.id,
                ep_number=episode.ep_number,
                title=episode.title,
                air_date=_parse_air_date(episode.air_date),
            )
        )
    anime.episode_count_expected = len(metadata.episodes)


async def _reparse_episode_numbers(session: AsyncSession) -> int:
    """Re-derives every episode number from its filename. Works purely off
    the stored paths, so it repairs numbers even while the share is offline --
    the scan does the same, but only for files it can actually see."""
    fixed = 0
    for episode in (await session.execute(select(LocalEpisode))).scalars().all():
        if episode.manual_override:
            continue
        parsed = guess_episode_number(os.path.basename(episode.file_path))
        if parsed != episode.ep_number:
            episode.ep_number = parsed
            fixed += 1
    return fixed


def _parse_air_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None
