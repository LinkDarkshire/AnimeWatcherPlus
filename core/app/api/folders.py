from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.repositories import FolderRepo
from app.services.scanner import has_video_files
from app.services.settings_store import forget_kept_empty_dir, remember_kept_empty_dir
from app.state import AppState

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


class FolderCreate(BaseModel):
    path: str
    type: str  # "content" | "download"
    name: str | None = None


class FolderOut(BaseModel):
    id: int
    path: str
    type: str
    name: str
    active: bool
    offline: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[FolderOut])
async def list_folders(session: AsyncSession = Depends(get_db)) -> list[FolderOut]:
    folders = await FolderRepo(session).list_all()
    return [FolderOut.model_validate(f) for f in folders]


@router.post("", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreate,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> FolderOut:
    if payload.type not in ("content", "download"):
        raise HTTPException(status_code=422, detail="type muss 'content' oder 'download' sein")
    path = Path(payload.path)
    if not path.is_dir():
        raise HTTPException(status_code=422, detail="Pfad existiert nicht oder ist kein Verzeichnis")

    repo = FolderRepo(session)
    if await repo.get_by_path(str(path)) is not None:
        raise HTTPException(status_code=409, detail="Ordner ist bereits registriert")

    folder = await repo.create(str(path), payload.type, payload.name or path.name)
    state.scanner.watch_folder(folder)
    # Scan runs in the background (job queue) so this request returns
    # immediately even for large folders; the UI picks up results live via WS.
    state.job_queue.enqueue("scan", lambda: state.scanner.full_scan_folder(folder))
    return FolderOut.model_validate(folder)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: int,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> None:
    repo = FolderRepo(session)
    folder = await repo.get(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    state.scanner.unwatch_folder(folder_id)
    await repo.delete(folder_id)


@router.post("/{folder_id}/rescan", status_code=202)
async def rescan_folder(
    folder_id: int,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> dict:
    repo = FolderRepo(session)
    folder = await repo.get(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    state.job_queue.enqueue("scan", lambda: state.scanner.full_scan_folder(folder))
    return {"status": "queued"}


class DeleteEmptyDirRequest(BaseModel):
    path: str


@router.post("/{folder_id}/delete-empty-dir", status_code=204)
async def delete_empty_dir(
    folder_id: int,
    payload: DeleteEmptyDirRequest,
    session: AsyncSession = Depends(get_db),
) -> None:
    repo = FolderRepo(session)
    folder = await repo.get(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")

    root = Path(folder.path).resolve()
    target = Path(payload.path).resolve()
    if target.parent != root:
        raise HTTPException(status_code=400, detail="Pfad ist kein direktes Unterverzeichnis des Ordners")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Verzeichnis nicht gefunden")
    if has_video_files(target):
        raise HTTPException(status_code=409, detail="Verzeichnis enthält mittlerweile Video-Dateien")

    shutil.rmtree(target)
    # It's gone -- no decision left to remember about it.
    await forget_kept_empty_dir(session, str(target))


@router.post("/{folder_id}/keep-empty-dir", status_code=204)
async def keep_empty_dir(
    folder_id: int,
    payload: DeleteEmptyDirRequest,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Remembers that the user wants this empty directory left alone. An
    empty directory gets no Anime row, so without persisting the decision the
    prompt would reappear on every scan."""
    folder = await FolderRepo(session).get(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Ordner nicht gefunden")
    target = Path(payload.path).resolve()
    if target.parent != Path(folder.path).resolve():
        raise HTTPException(status_code=400, detail="Pfad ist kein direktes Unterverzeichnis des Ordners")
    await remember_kept_empty_dir(session, str(target))
