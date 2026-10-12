from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_token(authorization: str | None = Header(default=None)) -> None:
    """Checks the bearer token on every API route. The core only listens on
    127.0.0.1, and the desktop shell hands the per-session token to the UI."""
    settings = get_settings()
    if not settings.sidecar_token:
        # No token configured (e.g. first dev run without the Tauri supervisor) -> open.
        return
    expected = f"Bearer {settings.sidecar_token}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")
