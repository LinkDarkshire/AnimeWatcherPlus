from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.state import AppState


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def get_app_state(request: Request) -> AppState:
    return request.app.state.awp
