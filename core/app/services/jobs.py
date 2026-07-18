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
    """Simple in-process pub/sub. WS-Gateway and internal services both subscribe.

    Kap. 4.3: "verteilt Domain-Events an Abonnenten (WS-Gateway, Auto-Sort)".
    """

    _subscribers: list[EventHandler] = field(default_factory=list)

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        logger.info("event_published", event_name=event, data=data)
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
    """Serializes long-running work (scan, identify, analyze, move, download) as jobs.

    A single background worker task processes jobs one at a time; this matches the
    "eine Writer-Verbindung" principle in Kap. 6.2 without needing a real queue broker.
    """

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

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            job.status = "running"
            try:
                await job.coro_factory()
                job.status = "done"
            except Exception as exc:  # noqa: BLE001 - isolate job failures (NFA-12)
                job.status = "failed"
                job.error = str(exc)
                logger.exception("job_failed", job_type=job.job_type, job_id=job.id)
            finally:
                self._queue.task_done()
