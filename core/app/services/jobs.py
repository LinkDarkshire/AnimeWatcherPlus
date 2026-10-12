from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class EventBus:
    """Simple in-process publish/subscribe. The WebSocket gateway forwards
    every event to the UI; internal services subscribe for their own needs."""

    _subscribers: list[EventHandler] = field(default_factory=list)

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        logger.debug("event_published", event_name=event, data=data)
        for handler in list(self._subscribers):
            try:
                await handler(payload)
            except Exception:
                logger.exception("event_handler_failed", event_name=event)


@dataclass
class Job:
    id: int
    job_type: str
    coro_factory: Callable[[], Awaitable[None]]
    status: str = "queued"  # queued|running|done|failed
    error: str | None = None


class JobQueue:
    """Runs long work (scans, identification, metadata refreshes) one job at a
    time in a single background task. Doing it serially keeps SQLite writes
    and AniDB requests from piling up on each other."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._next_id = 1
        self._worker_task: asyncio.Task | None = None
        self.jobs: dict[int, Job] = {}

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    def enqueue(self, job_type: str, coro_factory: Callable[[], Awaitable[None]]) -> Job:
        job = Job(id=self._next_id, job_type=job_type, coro_factory=coro_factory)
        self._next_id += 1
        self.jobs[job.id] = job
        self._queue.put_nowait(job)
        return job

    def pending_count(self, job_types: frozenset[str] | set[str]) -> int:
        """Queued or running jobs of these types."""
        return sum(1 for job in self.jobs.values() if job.job_type in job_types)

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            job.status = "running"
            try:
                await job.coro_factory()
                job.status = "done"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                logger.exception("job_failed", job_type=job.job_type, job_id=job.id)
            finally:
                # Only queued and running jobs are kept; finished ones would
                # otherwise pile up for as long as the app runs.
                self.jobs.pop(job.id, None)
                self._queue.task_done()
