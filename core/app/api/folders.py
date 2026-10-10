from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.models import Folder
from app.db.repositories import FolderRepo
from app.services.media_files import APP_SIDECARS, has_user_files, remove_dir_if_empty
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


def _child_dir_of(folder: Folder, raw_path: str) -> Path:
    """Validates that `raw_path` is a direct subdirectory of the folder and
    returns it in the scanner's own spelling (`folder.path / name`).

    The containment check compares resolved paths, but the returned path must
    not be the resolved one: on Windows a mapped drive resolves to its UNC
    form, and a "keep" decision stored as `\\\\server\\share\\X` would never
    match the `Z:\\X` the scanner looks it up by."""
    target = Path(raw_path)
    if target.resolve().parent != Path(folder.path).resolve():
        raise HTTPException(status_code=400, detail="Pfad ist kein direktes Unterverzeichnis des Ordners")
    return Path(folder.path) / target.name


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

    target = _child_dir_of(folder, payload.path)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Verzeichnis nicht gefunden")
    # Checked here again, not just when the prompt was raised: files may have
    # arrived since (a download starting), and "no videos" alone was never
    # enough -- subtitles or archives must not be deleted with it.
    if has_user_files(target):
        raise HTTPException(status_code=409, detail="Verzeichnis ist nicht leer")

    for name in APP_SIDECARS:
        (target / name).unlink(missing_ok=True)
    if not remove_dir_if_empty(target):
        raise HTTPException(status_code=409, detail="Verzeichnis ist nicht leer")
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
    await remember_kept_empty_dir(session, str(_child_dir_of(folder, payload.path)))
