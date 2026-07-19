from __future__ import annotations

from pathlib import Path

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Anime
from app.db.repositories import AnimeRepo, JobLogRepo, LocalEpisodeRepo
from app.domain.metadata import AnimeMetadata
from app.providers.base import ProviderRegistry
from app.services import artwork, nfo
from app.services.jobs import EventBus
from app.services.titledump import fuzzy_match

logger = structlog.get_logger(__name__)


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
    try:
        anime = await anime_repo.apply_identification(
            anime_id,
            anidb_id=anidb_id,
            title=metadata.title,
            original_title=metadata.original_title,
            alt_titles=metadata.alt_titles,
            year=metadata.year,
            media_type=metadata.media_type,
            description=metadata.description,
            tags=[(t.name, t.weight, t.anidb_tag_id) for t in metadata.tags],
            expected_episodes=[(e.ep_number, e.title) for e in metadata.episodes],
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
        anime = await anime_repo.mark_conflicted(anime_id, anidb_id, metadata.title)
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

    has_poster = await _write_artwork_and_aniinfo(
        session, provider_registry, provider_name, anime, anime_dir, anidb_id, match_score,
        force_poster_refresh=id_changed,
    )

    nfo.write_tvshow_nfo(
        anime_dir,
        anidb_id=anidb_id,
        title=metadata.title,
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

    return anime


async def _write_artwork_and_aniinfo(
    session: AsyncSession,
    provider_registry: ProviderRegistry,
    provider_name: str | None,
    anime: Anime,
    anime_dir: Path,
    anidb_id: int,
    match_score: float | None,
    *,
    force_poster_refresh: bool = False,
) -> bool:
    """Best-effort: a failure here must never break identification itself
    (NFA-12-style isolation), so every error is caught and logged.
    Returns True if a poster was (already, or newly) saved locally.

    `force_poster_refresh` is set when the AniDB ID just changed (e.g. via
    the "change AniDB ID" duplicate-resolution flow): the previously saved
    poster belongs to the *old* identity, so it must be deleted and
    re-downloaded rather than left in place just because *a* poster already
    exists.
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

    poster_saved = bool(anime.poster_path)
    poster_url = full_info.get("poster_url")
    if poster_url and (not poster_saved or force_poster_refresh):
        if force_poster_refresh:
            (anime_dir / artwork.POSTER_FILENAME).unlink(missing_ok=True)
            poster_saved = False
        try:
            async with httpx.AsyncClient() as client:
                poster_filename = await artwork.download_poster(client, poster_url, anime_dir)
        except Exception:
            logger.exception("poster_download_error", anime_id=anime.id)
            poster_filename = None
        if poster_filename:
            await anime_repo.set_poster_path(anime.id, poster_filename)
            poster_saved = True
        elif force_poster_refresh:
            # Old poster was already deleted and the re-download failed --
            # don't leave the DB pointing at a file that no longer exists.
            await anime_repo.set_poster_path(anime.id, None)

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
