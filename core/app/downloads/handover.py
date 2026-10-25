"""Sending a link that a link resolver has to work on first runs in the
background (see service.send / complete_handover): the request returns at
once, and the download list shows "resolving", then the progress -- or why
it failed -- instead of the app waiting for minutes without a word."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.db.session import session_scope
from app.downloads import service

if TYPE_CHECKING:
    from app.state import AppState

logger = structlog.get_logger(__name__)

_running: set[asyncio.Task[None]] = set()


def start(state: AppState, request_id: int) -> None:
    async def run() -> None:
        try:
            async with (state.session_factory or session_scope)() as session:
                await service.complete_handover(session, state.download_plugins, request_id)
        except Exception:
            logger.exception("download_handover_task_failed", request_id=request_id)
        await state.event_bus.publish("downloads.updated", {"request_id": request_id})

    task = asyncio.create_task(run())
    _running.add(task)
    task.add_done_callback(_running.discard)
