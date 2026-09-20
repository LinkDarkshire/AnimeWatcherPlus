from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Anime
from app.db.repositories import AnimeRepo, JobLogRepo, LocalEpisodeRepo
from app.domain.metadata import AnimeMetadata
from app.domain.titles import resolve_title, variants_from_metadata
from app.providers.base import ProviderRegistry
from app.services import artwork, nfo, sorter
from app.services.jobs import EventBus
from app.services.settings_store import get_display_title_order, get_staleness_config
from app.services.staleness import is_stale
from app.services.titledump import fuzzy_match

logger = structlog.get_logger(__name__)


def _parse_air_date(value: str | None) -> dt.date | None:
    """AniDB's <airdate> is normally YYYY-MM-DD, but the field is free text
    and sometimes missing/partial -- never let a malformed date break
    identification, just treat it as unknown."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


async def identify_anime(
    session: AsyncSession,
    settings: Settings,
    anime: Anime,
    anime_dir: Path,
    provider_registry: ProviderRegistry,
    event_bus: EventBus,
) -> Anime:
    """Orchestrates: NFO -> local titledump fuzzy match -> provider chain -> NFO write.

    Mirrors the Kap. 4.4 sequence diagram. Ambiguous fuzzy matches go to `review`
    instead of a silent auto-assignment (Edge Case 4 / FA-26); no match at all goes
    to `needs_manual_id` (FA-07).
    """
    anime_repo = AnimeRepo(session)
    job_log = JobLogRepo(session)

    anidb_id = nfo.read_anidb_id_from_nfo(anime_dir)
    match_score: float | None = None

    if anidb_id is not None:
        logger.info("identification_nfo_hit", anime_id=anime.id, anidb_id=anidb_id)
    else:
        candidates = await fuzzy_match(session, anime_dir.name)
        if not candidates:
            anime.ident_status = "needs_manual_id"
            await session.commit()
            await job_log.add("identify", "needs_manual_id", "no title-dump candidates", anime.id)
            await event_bus.publish("anime.needs_review", {"anime_id": anime.id, "candidates": []})
            return anime

        top = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        confident = top.score >= settings.fuzzy_score_threshold and (
            len(candidates) == 1 or (top.score - second_score) >= settings.fuzzy_top2_delta_threshold
        )
        if confident:
            anidb_id = top.aid
            match_score = top.score
        else:
            anime.ident_status = "review"
            review_candidates = [{"aid": c.aid, "title": c.title, "score": c.score} for c in candidates]
            anime.review_candidates = review_candidates
            await session.commit()
            await job_log.add("identify", "needs_review", f"ambiguous match: {review_candidates}", anime.id)
            await event_bus.publish(
                "anime.needs_review", {"anime_id": anime.id, "candidates": review_candidates}
            )
            return anime

    metadata, provider_name = await provider_registry.fetch_chain({"anidb": str(anidb_id)})
    if metadata is None:
        await job_log.add("identify", "provider_fetch_failed", f"anidb_id={anidb_id}", anime.id)
        logger.warning("identification_provider_fetch_failed", anime_id=anime.id, anidb_id=anidb_id)
        return anime

    return await _finalize_identification(
        session,
        anime_repo,
        job_log,
        event_bus,
        provider_registry,
        anime,
        anime_dir,
        anidb_id,
        metadata,
        provider_name,
        match_score,
        job_result="identified",
    )


async def manual_identify(
    session: AsyncSession,
    settings: Settings,
    anime: Anime,
    anime_dir: Path,
    anidb_id: int,
    provider_registry: ProviderRegistry,
    event_bus: EventBus,
) -> Anime:
    """FA-07: user-supplied AniDB ID, bypassing the fuzzy-match step entirely."""
    anime_repo = AnimeRepo(session)
    job_log = JobLogRepo(session)

    metadata, provider_name = await provider_registry.fetch_chain({"anidb": str(anidb_id)})
    if metadata is None:
        await job_log.add("identify", "manual_provider_fetch_failed", f"anidb_id={anidb_id}", anime.id)
        raise ValueError(f"AniDB provider returned no data for aid={anidb_id}")

    return await _finalize_identification(
        session,
        anime_repo,
        job_log,
        event_bus,
        provider_registry,
        anime,
        anime_dir,
        anidb_id,
        metadata,
        provider_name,
        match_score=None,
        job_result="manual_identified",
    )


async def _finalize_identification(
    session: AsyncSession,
    anime_repo: AnimeRepo,
    job_log: JobLogRepo,
    event_bus: EventBus,
    provider_registry: ProviderRegistry,
    anime: Anime,
    anime_dir: Path,
    anidb_id: int,
    metadata: AnimeMetadata,
    provider_name: str | None,
    match_score: float | None,
    job_result: str,
) -> Anime:
    """Shared tail of identify_anime/manual_identify: persist metadata, write
    tvshow.nfo, then (best-effort, never fatal) the poster + aniinfo.json
    sidecar with everything the provider knows beyond the lean AnimeMetadata
    contract.
    """
    anime_id = anime.id  # captured up front: session.rollback() below expires
    # every attribute on every object in the session, and re-accessing
    # anime.id afterwards would trigger a lazy DB reload outside a valid
    # greenlet context (MissingGreenlet), not just return the cached value.
    previous_anidb_id = anime.anidb_id  # for the poster-refresh + duplicate-group fixup below

    # The provider resolved a primary title using its own default order; the
    # stored display name has to follow the user's configured one instead.
    # `metadata.title` stays the fallback for anime whose variants AniDB
    # doesn't supply at all.
    variants = variants_from_metadata(metadata)
    display_title = resolve_title(variants, await get_display_title_order(session), metadata.title)

    try:
        anime = await anime_repo.apply_identification(
            anime_id,
            anidb_id=anidb_id,
            title=display_title,
            original_title=metadata.original_title,
            title_variants=variants,
            alt_titles=metadata.alt_titles,
            year=metadata.year,
            media_type=metadata.media_type,
            description=metadata.description,
            tags=[(t.name, t.weight, t.anidb_tag_id) for t in metadata.tags],
            expected_episodes=[
                (e.ep_number, e.title, _parse_air_date(e.air_date)) for e in metadata.episodes
            ],
            ident_status="identified",
            match_score=match_score,
            provider=provider_name,
            external_id=str(anidb_id),
        )
    except IntegrityError:
        # Defense-in-depth: apply_identification's own duplicate check
        # (querying for another row with this anidb_id) should always avoid
        # this by flagging is_duplicate instead of writing a second row with
        # the same id, but if the DB schema is ever in an inconsistent state
        # (e.g. two processes migrating the same SQLite file at once), a
        # bare UNIQUE-constraint crash must never take the job down with it.
        await session.rollback()
        logger.exception(
            "apply_identification_integrity_error_falling_back_to_review",
            anime_id=anime_id,
            anidb_id=anidb_id,
        )
        anime = await anime_repo.mark_conflicted(anime_id, anidb_id, display_title)
        await job_log.add(
            "identify",
            "db_conflict",
            f"anidb_id={anidb_id}: UNIQUE constraint violated despite duplicate check; "
            f"flagged for manual review instead of crashing the job",
            anime_id,
        )
        await event_bus.publish(
            "anime.needs_review",
            {"anime_id": anime_id, "candidates": anime.review_candidates},
        )
        return anime

    anime.review_candidates = None
    await session.commit()

    id_changed = previous_anidb_id is not None and previous_anidb_id != anidb_id
    await anime_repo.recompute_duplicate_flags(anidb_id)
    if id_changed:
        await anime_repo.recompute_duplicate_flags(previous_anidb_id)

    # Keep the persisted no_scan verdict current -- but asymmetrically:
    # newly crossing the staleness threshold sets it on *any* refresh
    # (that's the normal, ongoing detection every rescan must be able to
    # make), while *clearing* it back to False only ever happens as a
    # side effect of an actual AniDB-ID change (the duplicate-resolution
    # "change ID" flow). A same-ID refresh -- including a user-triggered
    # "Force Full Scan" that deliberately re-checks every anime regardless
    # of no_scan -- must never silently un-flag something on its own; the
    # user has to explicitly reassign the ID to make it reconsidered.
    # anime_repo.get() eager-loads expected_episodes -- is_stale() needs
    # that and `anime` here may not have it loaded.
    threshold_days, rule_enabled = await get_staleness_config(session)
    fresh_anime = await anime_repo.get(anime_id)
    if fresh_anime is not None:
        # None only if the row vanished mid-identification (a folder deleted
        # while its job ran); nothing left to flag then.
        currently_stale = bool(rule_enabled and is_stale(fresh_anime, threshold_days))
        if currently_stale:
            if not fresh_anime.no_scan:
                await anime_repo.set_no_scan(anime_id, True)
            anime.no_scan = True
        elif id_changed and fresh_anime.no_scan:
            await anime_repo.set_no_scan(anime_id, False)
            anime.no_scan = False
        else:
            anime.no_scan = fresh_anime.no_scan

    if id_changed and anime.poster_path:
        # The old poster belongs to the *previous* identity -- clear it
        # unconditionally, before even attempting the new fetch below. This
        # must not be nested inside the fetch-dependent logic in
        # _write_artwork_and_aniinfo: if the new ID's get_full_info() call
        # fails, returns no poster_url, or the redownload itself fails, the
        # stale file+DB pointer would otherwise silently survive the ID
        # change (the actual bug this fixes).
        (anime_dir / artwork.POSTER_FILENAME).unlink(missing_ok=True)
        await anime_repo.set_poster_path(anime_id, None)
        anime.poster_path = None

    has_poster = await _write_artwork_and_aniinfo(
        session, provider_registry, provider_name, anime, anime_dir, anidb_id, match_score
    )

    nfo.write_tvshow_nfo(
        anime_dir,
        anidb_id=anidb_id,
        title=display_title,
        original_title=metadata.original_title,
        year=metadata.year,
        description=metadata.description,
        tags=[t.name for t in metadata.tags],
        has_local_poster=has_poster,
    )

    await job_log.add("identify", job_result, f"anidb_id={anidb_id} provider={provider_name}", anime.id)
    await event_bus.publish(
        "anime.identified", {"anime_id": anime.id, "anidb_id": anidb_id, "score": match_score}
    )

    if anime.is_duplicate:
        logger.warning(
            "anime_duplicate_detected",
            anime_id=anime.id,
            anidb_id=anidb_id,
            duplicate_of_anime_id=anime.duplicate_of_anime_id,
        )
        await job_log.add(
            "identify",
            "duplicate_detected",
            f"anidb_id={anidb_id} duplicate_of_anime_id={anime.duplicate_of_anime_id}",
            anime.id,
        )
        await event_bus.publish(
            "anime.duplicate_detected",
            {"anime_id": anime.id, "anidb_id": anidb_id, "duplicate_of_anime_id": anime.duplicate_of_anime_id},
        )

    # Must run last: on sort_mode="auto" with an unambiguous target, this can
    # delete `anime`'s own row (merged into an existing content-folder copy)
    # -- everything above that still needs anime.id for job-log/event
    # bookkeeping has to happen first.
    await sorter.maybe_auto_sort(session, event_bus, anime.id)
    # Runs after sorting: if the anime just got auto-sorted, its directory
    # and files already match the canonical scheme (sort_anime uses the same
    # naming helper), so this is a harmless no-op in that case -- but it's
    # what normalizes anime that were never sorted at all (already in the
    # right folder, e.g. long-standing content-folder entries).
    await sorter.maybe_auto_rename(session, event_bus, anime.id)
    # Last of all: episode NFOs have to name the files as they finally are,
    # so this must follow both the move and the rename.
    await _write_episode_nfos(session, anime_id, anidb_id)

    return anime


async def _write_episode_nfos(session: AsyncSession, anime_id: int, anidb_id: int) -> int:
    """FA-09: one Jellyfin/Kodi `episodedetails` NFO per matched episode file.

    Best-effort like the poster/aniinfo sidecars -- a read-only share or a
    single unwritable file must never fail the identification that produced
    the metadata. Unmatched files are skipped: without a confirmed episode
    number there is nothing truthful to write.
    """
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None:
        # Auto-sort merged this entry into an existing one and deleted the row;
        # the surviving anime writes its own NFOs on its next identification.
        return 0

    local_episodes = await LocalEpisodeRepo(session).by_anime(anime_id)
    written = 0
    for local, expected in sorter.match_local_episodes(local_episodes, anime.expected_episodes):
        if expected is None:
            continue
        try:
            if nfo.write_episode_nfo(
                Path(local.file_path),
                title=expected.title,
                ep_number=expected.ep_number,
                anidb_id=anidb_id,
            ):
                written += 1
        except OSError:
            logger.warning("episode_nfo_write_failed", anime_id=anime_id, path=local.file_path)
    if written:
        logger.info("episode_nfos_written", anime_id=anime_id, count=written)
    return written


async def _write_artwork_and_aniinfo(
    session: AsyncSession,
    provider_registry: ProviderRegistry,
    provider_name: str | None,
    anime: Anime,
    anime_dir: Path,
    anidb_id: int,
    match_score: float | None,
) -> bool:
    """Best-effort: a failure here must never break identification itself
    (NFA-12-style isolation), so every error is caught and logged.
    Returns True if a poster was (already, or newly) saved locally.
    """
    if provider_name is None:
        return False
    provider = provider_registry.get_provider(provider_name)
    if provider is None:
        return False

    try:
        full_info = await provider.get_full_info(str(anidb_id))
    except Exception:
        logger.exception("get_full_info_failed", anime_id=anime.id, anidb_id=anidb_id)
        return False
    if full_info is None:
        return False

    anime_repo = AnimeRepo(session)
    episode_repo = LocalEpisodeRepo(session)
    local_count = len(await episode_repo.by_anime(anime.id))

    # Checking the DB field alone isn't enough: a directory reorganized
    # outside the app (moved/renamed by hand, or by an external tool, before
    # or between AnimeWatcherPlus runs) can leave poster_path pointing at a
    # file that no longer exists at the anime's current directory -- and
    # since that's indistinguishable from "already saved" if only the DB
    # column is checked, no rescan would ever notice or re-download it.
    # Verifying the file's actual presence makes this self-healing on the
    # very next identify/rescan, regardless of why it went missing.
    poster_path = anime.poster_path
    poster_saved = poster_path is not None and (anime_dir / poster_path).is_file()
    poster_url = full_info.get("poster_url")
    if poster_url and not poster_saved:
        try:
            async with httpx.AsyncClient() as client:
                poster_filename = await artwork.download_poster(client, poster_url, anime_dir)
        except Exception:
            logger.exception("poster_download_error", anime_id=anime.id)
            poster_filename = None
        if poster_filename:
            await anime_repo.set_poster_path(anime.id, poster_filename)
            poster_saved = True

    try:
        artwork.write_aniinfo_json(
            anime_dir,
            full_info,
            episode_count_local=local_count,
            ident_status="identified",
            match_score=match_score,
        )
    except OSError:
        logger.exception("aniinfo_write_failed", anime_id=anime.id)

    return poster_saved
