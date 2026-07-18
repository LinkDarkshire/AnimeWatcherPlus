from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.models import Anime
from app.db.repositories import AnimeRepo
from app.services import identification
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
    missing_on_disk: bool
    is_duplicate: bool
    duplicate_of_anime_id: int | None


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


def _to_list_item(anime: Anime) -> AnimeListItem:
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
        missing_on_disk=anime.missing_on_disk,
        is_duplicate=anime.is_duplicate,
        duplicate_of_anime_id=anime.duplicate_of_anime_id,
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
    page: int = 1,
    size: int = 50,
    session: AsyncSession = Depends(get_db),
) -> AnimeListResponse:
    repo = AnimeRepo(session)
    items, total = await repo.search(
        query=query, year=year, media_type=type, tag=tag, status_filter=status, page=page, size=size
    )
    return AnimeListResponse(total=total, page=page, items=[_to_list_item(a) for a in items])


@router.get("/animes/{anime_id}", response_model=AnimeDetail)
async def get_anime(anime_id: int, session: AsyncSession = Depends(get_db)) -> AnimeDetail:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    threshold_days, _ = await get_staleness_config(session)
    return _to_detail(anime, threshold_days)


@public_router.get("/animes/{anime_id}/poster")
async def get_anime_poster(anime_id: int, session: AsyncSession = Depends(get_db)) -> FileResponse:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None or not anime.poster_path:
        raise HTTPException(status_code=404, detail="Kein Artwork vorhanden")
    poster_file = Path(anime.directory_path) / POSTER_FILENAME
    if not poster_file.is_file():
        raise HTTPException(status_code=404, detail="Artwork-Datei fehlt auf der Platte")
    return FileResponse(poster_file, media_type="image/jpeg")


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
    anime = await repo.get(anime_id)
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
