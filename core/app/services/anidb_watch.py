from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog

from app.providers.anidb import AniDBProvider

logger = structlog.get_logger(__name__)

CHECK_INTERVAL_S = 30.0

ResumeCallback = Callable[[], Awaitable[int]]


class AniDBBlockWatcher:
    """Notices when an AniDB ban, the daily limit or the failure pause ends,
    and puts the work that failed meanwhile back in the queue. Without it,
    anime that couldn't be identified during a ban stayed unidentified until
    the next restart or scan."""

    def __init__(self, provider: AniDBProvider, resume: list[ResumeCallback]) -> None:
        self._provider = provider
        self._resume = resume
        self._was_blocked = provider.blocked()[0] is not None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def check(self) -> int:
        """One check; returns how many jobs were re-queued (0 unless a block
        just ended)."""
        reason, _ = self._provider.blocked()
        blocked = reason is not None
        resumed = 0
        if self._was_blocked and not blocked:
            for callback in self._resume:
                try:
                    resumed += await callback()
                except Exception:  # one failing source of work mustn't stop the others
                    logger.exception("anidb_resume_failed")
            self._provider.activity.resumed_at = time.time()
            logger.info("anidb_work_resumed", jobs=resumed)
        if blocked != self._was_blocked or resumed:
            await self._provider.activity.notify()
        self._was_blocked = blocked
        return resumed

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_S)
            try:
                await self.check()
            except Exception:
                logger.exception("anidb_block_watch_failed")
