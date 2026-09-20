from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.completeness import Completeness, CompletenessRepo
from app.db.models import Anime
from app.db.repositories import AnimeRepo, LocalEpisodeRepo
from app.services import identification, sorter
from app.services.artwork import POSTER_FILENAME
from app.services.settings_store import get_staleness_config
from app.services.staleness import is_stale, last_episode_air_date
from app.state import AppState

router = APIRouter(prefix="/api/v1", tags=["animes"])

# Deliberately NOT registered with the bearer-token dependency in main.py:
# an <img src="..."> tag can't send an Authorization header (same constraint
# that already made the /ws token a query param). Only ever serves the fixed
# poster.jpg inside a known anime's own directory -- no user-supplied path
# component, so there's no traversal surface.
public_router = APIRouter(prefix="/api/v1", tags=["animes-public"])


class TagOut(BaseModel):
    name: str
    weight: int

    model_config = {"from_attributes": True}


class CompletenessOut(BaseModel):
    """FA-10: "vollständig / n fehlend" on the library card."""

    expected: int
    present: int
    missing: int


class AnimeListItem(BaseModel):
    id: int
    anidb_id: int | None
    title: str
    year: int | None
    media_type: str | None
    poster_path: str | None
    ident_status: str
    match_score: float | None
    episode_count_expected: int | None
    is_duplicate: bool
    duplicate_of_anime_id: int | None
    completeness: CompletenessOut | None


class AnimeListResponse(BaseModel):
    total: int
    page: int
    items: list[AnimeListItem]


class AnimeDetail(BaseModel):
    id: int
    anidb_id: int | None
    title: str
    original_title: str | None
    alt_titles: list[str]
    year: int | None
    media_type: str | None
    description: str | None
    poster_path: str | None
    ident_status: str
    match_score: float | None
    episode_count_expected: int | None
    directory_path: str
    tags: list[TagOut]
    review_candidates: list[dict] | None
    is_duplicate: bool
    duplicate_of_anime_id: int | None
    last_metadata_refresh: dt.datetime | None
    last_episode_air_date: dt.date | None
    is_stale: bool


def _poster_url(anime: Anime) -> str | None:
    if not anime.poster_path:
        return None
    return f"/api/v1/animes/{anime.id}/poster"


def _to_completeness(value: Completeness | None) -> CompletenessOut | None:
    """None for anime the comparison can't say anything about (not yet
    identified, or a provider entry with no numbered episodes at all) -- the
    card then shows no completeness badge rather than a misleading "0 of 0"."""
    if value is None or value.expected == 0:
        return None
    return CompletenessOut(expected=value.expected, present=value.present, missing=value.missing)


def _to_list_item(anime: Anime, completeness: Completeness | None = None) -> AnimeListItem:
    return AnimeListItem(
        id=anime.id,
        anidb_id=anime.anidb_id,
        title=anime.title,
        year=anime.year,
        media_type=anime.media_type,
        poster_path=_poster_url(anime),
        ident_status=anime.ident_status,
        match_score=anime.match_score,
        episode_count_expected=anime.episode_count_expected,
        is_duplicate=anime.is_duplicate,
        duplicate_of_anime_id=anime.duplicate_of_anime_id,
        completeness=_to_completeness(completeness),
    )


def _to_detail(anime: Anime, staleness_threshold_days: float) -> AnimeDetail:
    return AnimeDetail(
        id=anime.id,
        anidb_id=anime.anidb_id,
        title=anime.title,
        original_title=anime.original_title,
        alt_titles=anime.alt_titles or [],
        year=anime.year,
        media_type=anime.media_type,
        description=anime.description,
        poster_path=_poster_url(anime),
        ident_status=anime.ident_status,
        match_score=anime.match_score,
        episode_count_expected=anime.episode_count_expected,
        directory_path=anime.directory_path,
        tags=[TagOut(name=at.tag.name, weight=at.weight) for at in anime.tags],
        review_candidates=anime.review_candidates,
        is_duplicate=anime.is_duplicate,
        duplicate_of_anime_id=anime.duplicate_of_anime_id,
        last_metadata_refresh=anime.last_metadata_refresh,
        last_episode_air_date=last_episode_air_date(anime),
        is_stale=is_stale(anime, staleness_threshold_days),
    )


@router.get("/animes", response_model=AnimeListResponse)
async def list_animes(
    query: str | None = None,
    tag: str | None = None,
    year: int | None = None,
    type: str | None = None,
    status: str | None = None,
    missing: bool = False,
    page: int = 1,
    size: int = 50,
    session: AsyncSession = Depends(get_db),
) -> AnimeListResponse:
    repo = AnimeRepo(session)
    items, total = await repo.search(
        query=query,
        year=year,
        media_type=type,
        tag=tag,
        status_filter=status,
        page=page,
        size=size,
        missing_only=missing,
    )
    # Two grouped queries for the whole page, not one per card.
    completeness = await CompletenessRepo(session).for_animes([a.id for a in items])
    return AnimeListResponse(
        total=total,
        page=page,
        items=[_to_list_item(a, completeness.get(a.id)) for a in items],
    )


@router.get("/animes/{anime_id}", response_model=AnimeDetail)
async def get_anime(anime_id: int, session: AsyncSession = Depends(get_db)) -> AnimeDetail:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    threshold_days, _ = await get_staleness_config(session)
    return _to_detail(anime, threshold_days)


@router.delete("/animes/{anime_id}", status_code=204)
async def delete_anime(anime_id: int, session: AsyncSession = Depends(get_db)) -> None:
    """Removes one catalog entry -- used to resolve a confirmed duplicate
    (same anime cataloged from two folders). Does not touch files on disk."""
    repo = AnimeRepo(session)
    anime = await repo.get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    await repo.delete(anime_id)


@public_router.get("/animes/{anime_id}/poster")
async def get_anime_poster(anime_id: int, session: AsyncSession = Depends(get_db)) -> FileResponse:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None or not anime.poster_path:
        raise HTTPException(status_code=404, detail="Kein Artwork vorhanden")
    poster_file = Path(anime.directory_path) / POSTER_FILENAME
    if not poster_file.is_file():
        raise HTTPException(status_code=404, detail="Artwork-Datei fehlt auf der Platte")
    return FileResponse(poster_file, media_type="image/jpeg")


class MissingEpisodeOut(BaseModel):
    ep_number: str
    title: str | None
    air_date: dt.date | None


class MissingEpisodesResponse(BaseModel):
    anime_id: int
    expected: int
    present: int
    missing: list[MissingEpisodeOut]


@router.get("/animes/{anime_id}/missing-episodes", response_model=MissingEpisodesResponse)
async def get_missing_episodes(
    anime_id: int, session: AsyncSession = Depends(get_db)
) -> MissingEpisodesResponse:
    """FA-12, per series: which episodes of the provider's list have no file
    on disk. Specials/credits/trailers are excluded -- see
    db.completeness._is_plain_number."""
    if await AnimeRepo(session).get(anime_id) is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    repo = CompletenessRepo(session)
    counts = (await repo.for_animes([anime_id]))[anime_id]
    missing = await repo.missing_for_anime(anime_id)
    return MissingEpisodesResponse(
        anime_id=anime_id,
        expected=counts.expected,
        present=counts.present,
        missing=[
            MissingEpisodeOut(ep_number=m.ep_number, title=m.title, air_date=m.air_date)
            for m in missing
        ],
    )


class IncompleteAnime(BaseModel):
    anime_id: int
    title: str
    poster_path: str | None
    year: int | None
    media_type: str | None
    expected: int
    present: int
    missing: int


class MissingEpisodesOverview(BaseModel):
    total: int
    page: int
    items: list[IncompleteAnime]


@router.get("/missing-episodes", response_model=MissingEpisodesOverview)
async def list_missing_episodes(
    page: int = 1, size: int = 50, session: AsyncSession = Depends(get_db)
) -> MissingEpisodesOverview:
    """FA-12, global view. Paginated like the library -- on a large catalog
    this list can itself run into the hundreds."""
    repo = CompletenessRepo(session)
    rows, total = await repo.list_incomplete(page=page, size=size)
    counts = await repo.for_animes([anime.id for anime, _ in rows])
    return MissingEpisodesOverview(
        total=total,
        page=page,
        items=[
            IncompleteAnime(
                anime_id=anime.id,
                title=anime.title,
                poster_path=_poster_url(anime),
                year=anime.year,
                media_type=anime.media_type,
                expected=counts[anime.id].expected,
                present=counts[anime.id].present,
                missing=missing_count,
            )
            for anime, missing_count in rows
        ],
    )


class LocalEpisodeOut(BaseModel):
    id: int
    file_name: str
    ep_number: str | None
    manual_override: bool


@router.get("/animes/{anime_id}/episodes", response_model=list[LocalEpisodeOut])
async def list_local_episodes(
    anime_id: int, session: AsyncSession = Depends(get_db)
) -> list[LocalEpisodeOut]:
    """The files actually on disk with the episode number parsed from each
    filename -- the input for the manual correction below."""
    if await AnimeRepo(session).get(anime_id) is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    episodes = await LocalEpisodeRepo(session).by_anime(anime_id)
    episodes.sort(key=lambda e: (e.ep_number is None, _sort_key(e.ep_number), e.file_path))
    return [
        LocalEpisodeOut(
            id=e.id,
            file_name=Path(e.file_path).name,
            ep_number=e.ep_number,
            manual_override=e.manual_override,
        )
        for e in episodes
    ]


def _sort_key(ep_number: str | None) -> tuple[int, str]:
    """Numeric episodes in numeric order, anything else alphabetically after."""
    if ep_number is not None and ep_number.isdigit():
        return (int(ep_number), "")
    return (10**9, ep_number or "")


class EpisodeNumberUpdate(BaseModel):
    # null clears the manual correction and lets the next scan re-parse the
    # filename again.
    ep_number: str | None


@router.patch("/animes/{anime_id}/episodes/{episode_id}", response_model=LocalEpisodeOut)
async def update_local_episode_number(
    anime_id: int,
    episode_id: int,
    payload: EpisodeNumberUpdate,
    session: AsyncSession = Depends(get_db),
) -> LocalEpisodeOut:
    """Manual episode-number correction (concept Kap. 14: filename parsing
    can't cover every release naming scheme)."""
    repo = LocalEpisodeRepo(session)
    episode = await repo.get(episode_id)
    if episode is None or episode.anime_id != anime_id:
        raise HTTPException(status_code=404, detail="Episode nicht gefunden")
    ep_number = payload.ep_number.strip() if payload.ep_number else None
    if ep_number is not None and not ep_number.isdigit():
        raise HTTPException(status_code=422, detail="Episodennummer muss eine Zahl sein")

    updated = await repo.set_manual_ep_number(episode_id, ep_number)
    assert updated is not None
    return LocalEpisodeOut(
        id=updated.id,
        file_name=Path(updated.file_path).name,
        ep_number=updated.ep_number,
        manual_override=updated.manual_override,
    )


class FileRenameOut(BaseModel):
    current: str
    target: str


class RenameProposalOut(BaseModel):
    current_dir_name: str
    target_dir_name: str
    dir_needs_rename: bool
    file_renames: list[FileRenameOut]


class SortProposalOut(BaseModel):
    episode_count: int
    matched_count: int
    suggested_target_folder_id: int | None


class AnimePendingActions(BaseModel):
    """Everything on the Abfragen page that concerns this one series, so it
    can be resolved from the series itself. Identification (review) and
    duplicates are already part of the detail response; these are the two
    that weren't."""

    rename: RenameProposalOut | None
    sort: SortProposalOut | None


@router.get("/animes/{anime_id}/pending-actions", response_model=AnimePendingActions)
async def get_anime_pending_actions(
    anime_id: int, session: AsyncSession = Depends(get_db)
) -> AnimePendingActions:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")

    rename = await sorter.rename_proposal_for(session, anime)
    sort = await sorter.sort_proposal_for(session, anime)
    return AnimePendingActions(
        rename=(
            RenameProposalOut(
                current_dir_name=rename.current_dir_name,
                target_dir_name=rename.target_dir_name,
                dir_needs_rename=rename.dir_needs_rename,
                file_renames=[
                    FileRenameOut(current=current, target=target)
                    for current, target in rename.file_renames
                ],
            )
            if rename
            else None
        ),
        sort=(
            SortProposalOut(
                episode_count=sort.episode_count,
                matched_count=sort.matched_count,
                suggested_target_folder_id=sort.suggested_target_folder_id,
            )
            if sort
            else None
        ),
    )


class IdentifyRequest(BaseModel):
    anidb_id: int


@router.post("/animes/{anime_id}/identify", response_model=AnimeDetail)
async def identify_anime_manually(
    anime_id: int,
    payload: IdentifyRequest,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> AnimeDetail:
    repo = AnimeRepo(session)
    anime = await repo.get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    try:
        anime = await identification.manual_identify(
            session,
            state.settings,
            anime,
            Path(anime.directory_path),
            payload.anidb_id,
            state.provider_registry,
            state.event_bus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Re-read: identification may have merged this entry into an existing
    # copy (auto-sort) and deleted the row this request started from.
    anime = await repo.get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    threshold_days, _ = await get_staleness_config(session)
    return _to_detail(anime, threshold_days)


@router.post("/animes/{anime_id}/refresh-metadata", response_model=AnimeDetail)
async def refresh_metadata(
    anime_id: int,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> AnimeDetail:
    repo = AnimeRepo(session)
    anime = await repo.get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    if anime.anidb_id is None:
        raise HTTPException(status_code=409, detail="Anime ist noch nicht identifiziert")
    anime = await identification.manual_identify(
        session,
        state.settings,
        anime,
        Path(anime.directory_path),
        anime.anidb_id,
        state.provider_registry,
        state.event_bus,
    )
    threshold_days, _ = await get_staleness_config(session)
    return _to_detail(anime, threshold_days)


class RescanAllResponse(BaseModel):
    queued: int


@router.post("/animes/rescan-all", response_model=RescanAllResponse)
async def rescan_all(state: AppState = Depends(get_app_state)) -> RescanAllResponse:
    """Manual full-library metadata refresh, always ignoring the staleness
    rule -- the explicit "do it anyway" escape hatch alongside the automatic,
    rule-respecting rescan that runs on startup."""
    queued = await state.scanner.enqueue_metadata_rescan(ignore_staleness=True)
    return RescanAllResponse(queued=queued)


class DuplicateEntry(BaseModel):
    anime_id: int
    title: str
    directory_path: str
    poster_path: str | None


class DuplicateGroup(BaseModel):
    anidb_id: int
    title: str
    entries: list[DuplicateEntry]


@router.get("/duplicates", response_model=list[DuplicateGroup])
async def list_duplicates(session: AsyncSession = Depends(get_db)) -> list[DuplicateGroup]:
    """Groups of 2+ catalog entries sharing the same AniDB ID -- for each,
    the UI offers changing one entry's ID (misidentification) or deleting
    one entry (confirmed duplicate)."""
    groups = await AnimeRepo(session).list_duplicate_groups()
    return [
        DuplicateGroup(
            anidb_id=anidb_id,
            title=entries[0].title,
            entries=[
                DuplicateEntry(
                    anime_id=a.id,
                    title=a.title,
                    directory_path=a.directory_path,
                    poster_path=_poster_url(a),
                )
                for a in entries
            ],
        )
        for anidb_id, entries in groups
    ]


review_router = APIRouter(prefix="/api/v1/review-queue", tags=["review-queue"])


class ReviewItem(BaseModel):
    anime_id: int
    directory_path: str
    title_guess: str
    ident_status: str
    candidates: list[dict] | None


@review_router.get("", response_model=list[ReviewItem])
async def list_review_queue(session: AsyncSession = Depends(get_db)) -> list[ReviewItem]:
    repo = AnimeRepo(session)
    animes = await repo.list_needing_review_or_manual()
    return [
        ReviewItem(
            anime_id=a.id,
            directory_path=a.directory_path,
            title_guess=a.title,
            ident_status=a.ident_status,
            candidates=a.review_candidates,
        )
        for a in animes
    ]


class ReviewResolve(BaseModel):
    anidb_id: int


@review_router.post("/{anime_id}/resolve", response_model=AnimeDetail)
async def resolve_review(
    anime_id: int,
    payload: ReviewResolve,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> AnimeDetail:
    return await identify_anime_manually(
        anime_id, IdentifyRequest(anidb_id=payload.anidb_id), session=session, state=state
    )
