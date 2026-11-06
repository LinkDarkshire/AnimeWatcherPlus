from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.deps import get_db
from app.security import web
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


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def same_origin(headers: Mapping[str, str]) -> bool:
    """A browser's request comes from a page of this server itself (or
    names no origin at all, as same-origin GETs may)."""
    origin = headers.get("origin")
    if origin is None:
        return True
    # Behind a reverse proxy that passes on its own address as Host, the
    # browser's one comes as X-Forwarded-Host (a page can't set that header
    # on a browser's cross-site request).
    hosts = {headers.get("host", ""), *headers.get("x-forwarded-host", "").split(",")}
    return urlsplit(origin).netloc in {h.strip() for h in hosts if h.strip()}


async def web_session(db: AsyncSession, token: str | None) -> Session | None:
    """The web account behind a browser's session cookie, if valid."""
    if not token:
        return None
    account = await web.account_for_token(db, token)
    if account is None:
        return None
    return Session(device_id=None, is_admin=account.is_admin, expires_at=0.0, account_id=account.id)


async def _web_request_session(request: Request, db: AsyncSession) -> Session | None:
    session = await web_session(db, request.cookies.get(web.COOKIE_NAME))
    if session is None:
        return None
    # The cookie goes along with every request to this server, also ones a
    # foreign page makes the browser send: changes need the app's header.
    if request.method not in _SAFE_METHODS and (
        request.headers.get(web.WEB_HEADER) != "1" or not same_origin(request.headers)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Anfrage nicht von der Weboberfläche")
    return session


def desktop_token_ok(state: AppState, token: str | None) -> bool:
    expected = state.settings.sidecar_token
    if not expected:
        # No token configured (e.g. a dev run without the desktop shell): open.
        return True
    return token is not None and hmac.compare_digest(token, expected)


async def require_auth(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """Guards every API route. Desktop mode: the per-session token the
    desktop shell hands to its UI. Server mode: a short-lived access token a
    paired device got by signing a challenge with its key -- or, from the
    web interface, a browser's session cookie."""
    state = _state(request)
    token = _bearer(request)
    if state.settings.mode != "server":
        if not desktop_token_ok(state, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")
        return
    session = session_for_token(state, token) if token else await _web_request_session(request, db)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Anmeldung erforderlich")
    request.state.session = session


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """Like require_auth, but only admins (server mode): admin devices and
    web accounts. The desktop app's own core has a single user, who is its
    admin."""
    await require_auth(request, db)
    session: Session | None = getattr(request.state, "session", None)
    if session is not None and not session.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur für Admins")


async def require_asset_access(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """For URLs an <img> loads, which can't send headers: in server mode the
    access token comes as ?token= (or, in the web interface, the cookie goes
    along). In desktop mode these stay open as before (the core only listens
    on 127.0.0.1)."""
    state = _state(request)
    if state.settings.mode != "server":
        return
    token = _bearer(request) or request.query_params.get("token")
    if token:
        allowed = session_for_token(state, token) is not None
    else:
        allowed = await web_session(db, request.cookies.get(web.COOKIE_NAME)) is not None
    if not allowed:
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
            # Pairing and administration (import/export) are LAN only.
            is_lan_route = any(path == p or path.startswith(p + "/") for p in ("/pair", "/admin"))
            allowed = (is_lan_route or path == "/health") if on_pairing_port else not is_lan_route
            if not allowed:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4404})
                    return
                await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Not Found"}'})
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Server mode: what browsers should never do with the API's answers --
    guess content types, show them in frames, pass the address on, cache
    them. The app itself doesn't need any of it."""

    HEADERS: ClassVar[list[tuple[bytes, bytes]]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cache-control", b"no-store"),
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name for name, _ in message.get("headers", [])}
                extra = [(n, v) for n, v in self.HEADERS if n not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)
