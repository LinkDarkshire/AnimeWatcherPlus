from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import desktop_token_ok, same_origin, session_for_token, web_session
from app.db.session import session_scope
from app.security import web
from app.state import AppState

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    state: AppState = websocket.app.state.awp
    token = websocket.query_params.get("token")
    cookie = None if token else websocket.cookies.get(web.COOKIE_NAME)

    async def allowed() -> bool:
        if state.settings.mode != "server":
            return desktop_token_ok(state, token)
        if token:
            return session_for_token(state, token) is not None
        # The web interface: its cookie, and only from its own pages (a
        # WebSocket isn't bound by the same-origin policy).
        if not same_origin(websocket.headers):
            return False
        async with (state.session_factory or session_scope)() as db:
            return await web_session(db, cookie) is not None

    if not await allowed():
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def handler(payload: dict[str, Any]) -> None:
        # Server mode: the connection lives only as long as its token. A
        # revoked device loses it right away; everyone else reconnects with
        # their refreshed token. (A web session is checked when connecting.)
        if state.settings.mode == "server" and token and session_for_token(state, token) is None:
            await websocket.close(code=4401)
            return
        await websocket.send_json(payload)

    state.event_bus.subscribe(handler)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.event_bus.unsubscribe(handler)
