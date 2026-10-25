"""Once a download is done, its download folder is scanned again -- right
away, so the new episode shows up for sorting and renaming without waiting
for the next scan, and once more a little later, for clients that unpack
archives after finishing (JDownloader)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.db.models import Folder
from app.db.session import session_scope
from app.downloads import service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.state import AppState

logger = structlog.get_logger(__name__)

CHECK_INTERVAL_S = 60.0
LATE_RESCAN_DELAY_S = 180.0


class FinishedDownloadsWatcher:
    def __init__(self, state: AppState, sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]] = session_scope) -> None:
        self._state = state
        self._sessions = sessions
        self._task: asyncio.Task[None] | None = None
        self._late: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        for task in [self._task, *self._late]:
            if task is not None:
                task.cancel()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_S)
            try:
                await self.check()
            except Exception:
                logger.exception("finished_downloads_check_failed")

    async def check(self) -> int:
        """Returns how many downloads were newly found finished."""
        async with self._sessions() as session:
            done = await service.newly_finished(session, self._state.download_plugins)
            if not done:
                return 0
            folder_ids = {r.folder_id for r in done if r.folder_id is not None}
            query = select(Folder).where(Folder.type == "download", Folder.active.is_(True))
            if all(r.folder_id is not None for r in done):
                query = query.where(Folder.id.in_(folder_ids))
            folders = list((await session.execute(query)).scalars())

        logger.info("downloads_finished", count=len(done), titles=[r.title for r in done][:10])
        for folder in folders:
            self._rescan(folder)
            late = asyncio.create_task(self._rescan_later(folder))
            self._late.add(late)
            late.add_done_callback(self._late.discard)
        await self._state.event_bus.publish("downloads.finished", {"count": len(done)})
        return len(done)

    def _rescan(self, folder: Folder) -> None:
        scanner = self._state.scanner
        self._state.job_queue.enqueue("scan", lambda: scanner.full_scan_folder(folder))

    async def _rescan_later(self, folder: Folder) -> None:
        await asyncio.sleep(LATE_RESCAN_DELAY_S)
        self._rescan(folder)
