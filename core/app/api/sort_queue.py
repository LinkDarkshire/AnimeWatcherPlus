from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.repositories import AnimeRepo, FolderRepo
from app.services import sorter
from app.state import AppState

router = APIRouter(prefix="/api/v1/sort-queue", tags=["sort-queue"])


class SortQueueItem(BaseModel):
    anime_id: int
    title: str
    directory_path: str
    anidb_id: int
    episode_count: int
    matched_count: int
    suggested_target_folder_id: int | None


class SortResolveRequest(BaseModel):
    target_folder_id: int


class SortResolveResponse(BaseModel):
    moved: int
    unmatched: int
    target_anime_id: int


@router.get("", response_model=list[SortQueueItem])
async def list_sort_queue(session: AsyncSession = Depends(get_db)) -> list[SortQueueItem]:
    entries = await sorter.list_sort_queue(session)
    return [
        SortQueueItem(
            anime_id=e.anime_id,
            title=e.title,
            directory_path=e.directory_path,
            anidb_id=e.anidb_id,
            episode_count=e.episode_count,
            matched_count=e.matched_count,
            suggested_target_folder_id=e.suggested_target_folder_id,
        )
        for e in entries
    ]


@router.post("/{anime_id}/resolve", response_model=SortResolveResponse)
async def resolve_sort(
    anime_id: int,
    payload: SortResolveRequest,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> SortResolveResponse:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")
    source_folder = await FolderRepo(session).get(anime.folder_id)
    if source_folder is None or source_folder.type != "download":
        raise HTTPException(status_code=400, detail="Anime liegt nicht in einem Download-Ordner")
    if anime.ident_status != "identified":
        raise HTTPException(status_code=400, detail="Anime ist nicht identifiziert")

    target_folder = await FolderRepo(session).get(payload.target_folder_id)
    if target_folder is None:
        raise HTTPException(status_code=404, detail="Ziel-Ordner nicht gefunden")
    if target_folder.type != "content":
        raise HTTPException(status_code=400, detail="Ziel-Ordner ist kein Content-Ordner")

    try:
        result = await sorter.sort_anime(session, state.event_bus, anime_id, payload.target_folder_id)
    except sorter.SortConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SortResolveResponse(moved=result.moved, unmatched=result.unmatched, target_anime_id=result.target_anime_id)
