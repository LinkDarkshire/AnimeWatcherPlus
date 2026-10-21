from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import desktop_token_ok, session_for_token
from app.state import AppState

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    state: AppState = websocket.app.state.awp
    token = websocket.query_params.get("token")
    allowed = (
        session_for_token(state, token) is not None
        if state.settings.mode == "server"
        else desktop_token_ok(state, token)
    )
    if not allowed:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def handler(payload: dict[str, Any]) -> None:
        # Server mode: the connection lives only as long as its token. A
        # revoked device loses it right away; everyone else reconnects with
        # their refreshed token.
        if state.settings.mode == "server" and session_for_token(state, token) is None:
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
