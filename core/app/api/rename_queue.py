from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.repositories import AnimeRepo
from app.services import sorter
from app.state import AppState

router = APIRouter(prefix="/api/v1/rename-queue", tags=["rename-queue"])


class RenameQueueItem(BaseModel):
    anime_id: int
    title: str
    current_dir_name: str
    target_dir_name: str
    mismatched_file_count: int
    total_matched_episodes: int


class RenameResolveResponse(BaseModel):
    renamed_dir: bool
    renamed_files: int


@router.get("", response_model=list[RenameQueueItem])
async def list_rename_queue(session: AsyncSession = Depends(get_db)) -> list[RenameQueueItem]:
    entries = await sorter.list_rename_queue(session)
    return [
        RenameQueueItem(
            anime_id=e.anime_id,
            title=e.title,
            current_dir_name=e.current_dir_name,
            target_dir_name=e.target_dir_name,
            mismatched_file_count=e.mismatched_file_count,
            total_matched_episodes=e.total_matched_episodes,
        )
        for e in entries
    ]


@router.post("/{anime_id}/resolve", response_model=RenameResolveResponse)
async def resolve_rename(
    anime_id: int,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> RenameResolveResponse:
    anime = await AnimeRepo(session).get(anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime nicht gefunden")

    try:
        result = await sorter.rename_anime(session, state.event_bus, anime_id)
    except sorter.RenameConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RenameResolveResponse(renamed_dir=result.renamed_dir, renamed_files=result.renamed_files)
