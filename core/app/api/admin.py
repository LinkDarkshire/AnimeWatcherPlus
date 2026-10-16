from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.api.deps import get_app_state
from app.auth import require_admin
from app.downloads.registry import build_registry
from app.services import pending_actions, snapshot
from app.state import AppState

logger = structlog.get_logger(__name__)

# Moving the library between the desktop app and a server. Admin devices
# only; in server mode served on the LAN-only port (PortSeparationMiddleware),
# since an import replaces the whole library.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

MAX_SNAPSHOT_BYTES = 2 * 1024**3


class ImportOut(BaseModel):
    tables: int
    rows: int
    plugins: int
    cache_files: int
    unmapped_folders: list[str]


def _temp_file(state: AppState, suffix: str) -> Path:
    folder = state.settings.data_dir / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False)
    handle.close()
    return Path(handle.name)


@router.get("/export")
async def export_snapshot(state: AppState = Depends(get_app_state)) -> FileResponse:
    """The whole library as a snapshot zip (database, plugins, AniDB cache)."""
    target = _temp_file(state, ".zip")
    await asyncio.to_thread(snapshot.create_snapshot, state.settings, target)
    return FileResponse(
        target,
        media_type="application/zip",
        filename="animewatcherplus-snapshot.zip",
        background=BackgroundTask(target.unlink, missing_ok=True),
    )


@router.post("/import", response_model=ImportOut)
async def import_snapshot(
    request: Request,
    mappings: str = "[]",
    force: bool = False,
    state: AppState = Depends(get_app_state),
) -> ImportOut:
    """Replaces the library with an uploaded snapshot (request body: the
    zip). `mappings` is a JSON list of {"source", "target"} path prefixes.
    Refused if this core already has a library, unless `force`."""
    try:
        parsed = [snapshot.PathMapping(source=m["source"], target=m["target"]) for m in json.loads(mappings)]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Ungültige Pfad-Zuordnung") from exc
    if not force and not await asyncio.to_thread(snapshot.library_is_empty, state.settings.db_path):
        raise HTTPException(status_code=409, detail="Hier ist bereits eine Bibliothek vorhanden")

    upload = _temp_file(state, ".zip")
    try:
        size = 0
        with upload.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_SNAPSHOT_BYTES:
                    raise HTTPException(status_code=413, detail="Snapshot zu groß")
                out.write(chunk)

        # Nothing may scan or write while the library is being replaced.
        await state.scanner.stop()
        try:
            result = await asyncio.to_thread(snapshot.import_snapshot, state.settings, upload, parsed)
        except snapshot.SnapshotError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            state.download_plugins = await asyncio.to_thread(build_registry, state.settings.plugins_dir)
            await state.scanner.start()
    finally:
        upload.unlink(missing_ok=True)

    pending_actions.invalidate()
    await state.event_bus.publish("library.repaired", {"imported": True})
    return ImportOut(**vars(result))
