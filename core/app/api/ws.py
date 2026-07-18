from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.state import AppState

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    state: AppState = websocket.app.state.awp
    token = websocket.query_params.get("token")
    if state.settings.sidecar_token and token != state.settings.sidecar_token:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def handler(payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    state.event_bus.subscribe(handler)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.event_bus.unsubscribe(handler)
