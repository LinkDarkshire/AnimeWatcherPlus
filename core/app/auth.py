from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status
from starlette.types import ASGIApp, Receive, Scope, Send

from app.security.store import Session

if TYPE_CHECKING:
    from app.state import AppState


def _state(request: Request) -> AppState:
    return request.app.state.awp


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:] if header.lower().startswith("bearer ") else None


def session_for_token(state: AppState, token: str | None) -> Session | None:
    """The logged-in device behind a server-mode access token, if valid."""
    return state.security.session(token) if token else None


def desktop_token_ok(state: AppState, token: str | None) -> bool:
    expected = state.settings.sidecar_token
    if not expected:
        # No token configured (e.g. a dev run without the desktop shell): open.
        return True
    return token is not None and hmac.compare_digest(token, expected)


async def require_auth(request: Request) -> None:
    """Guards every API route. Desktop mode: the per-session token the
    desktop shell hands to its UI. Server mode: a short-lived access token a
    paired device got by signing a challenge with its key."""
    state = _state(request)
    token = _bearer(request)
    if state.settings.mode != "server":
        if not desktop_token_ok(state, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")
        return
    session = session_for_token(state, token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Anmeldung erforderlich")
    request.state.session = session


async def require_admin(request: Request) -> None:
    """Like require_auth, but only admin devices (server mode). The desktop
    app's own core has a single user, who is its admin."""
    await require_auth(request)
    session: Session | None = getattr(request.state, "session", None)
    if session is not None and not session.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur für Admin-Geräte")


async def require_asset_access(request: Request) -> None:
    """For URLs an <img> loads, which can't send headers: in server mode the
    access token comes as ?token=. In desktop mode these stay open as before
    (the core only listens on 127.0.0.1)."""
    state = _state(request)
    if state.settings.mode != "server":
        return
    token = _bearer(request) or request.query_params.get("token")
    if session_for_token(state, token) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Anmeldung erforderlich")


class PortSeparationMiddleware:
    """Server mode listens on two ports: the API (reachable from the
    internet through the reverse proxy) and pairing (LAN only, never
    forwarded). This keeps them strictly apart by the port a request came in
    on: pairing routes exist only on the pairing port, and the pairing port
    serves nothing else -- so even a misconfigured proxy can't expose
    pairing to the internet."""

    def __init__(self, app: ASGIApp, pairing_port: int) -> None:
        self.app = app
        self.pairing_port = pairing_port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            server = scope.get("server") or (None, None)
            on_pairing_port = server[1] == self.pairing_port
            path: str = scope["path"]
            is_pairing_route = path == "/pair" or path.startswith("/pair/")
            allowed = (is_pairing_route or path == "/health") if on_pairing_port else not is_pairing_route
            if not allowed:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4404})
                    return
                await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Not Found"}'})
                return
        await self.app(scope, receive, send)
