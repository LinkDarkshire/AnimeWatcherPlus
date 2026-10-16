from __future__ import annotations

import datetime as dt

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.auth import require_admin, require_auth
from app.db.models import Device
from app.security import devices
from app.security.keys import auth_message, verify_signature
from app.security.store import CHALLENGE_TTL_S
from app.state import AppState

logger = structlog.get_logger(__name__)

# Login (server mode): ask for a challenge, sign it, get a short-lived token.
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
# Device management for admin devices.
devices_router = APIRouter(prefix="/api/v1/devices", tags=["devices"])

_LOGIN_FAILED = "Anmeldung fehlgeschlagen"


def _server_only(state: AppState) -> None:
    if state.settings.mode != "server":
        raise HTTPException(status_code=404, detail="Nur im Server-Modus")


class ChallengeIn(BaseModel):
    device_id: int


class ChallengeOut(BaseModel):
    nonce: str
    expires_in: int


class TokenIn(BaseModel):
    device_id: int
    nonce: str
    signature: str  # base64 Ed25519 signature over keys.auth_message(device_id, nonce)


class TokenOut(BaseModel):
    token: str
    expires_in: int
    device_id: int
    is_admin: bool


@router.post("/challenge", response_model=ChallengeOut)
async def challenge(
    payload: ChallengeIn, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> ChallengeOut:
    _server_only(state)
    if await devices.active_device(session, payload.device_id) is None:
        raise HTTPException(status_code=401, detail=_LOGIN_FAILED)
    return ChallengeOut(nonce=state.security.new_challenge(payload.device_id), expires_in=CHALLENGE_TTL_S)


@router.post("/token", response_model=TokenOut)
async def token(
    payload: TokenIn, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> TokenOut:
    _server_only(state)
    # The nonce is consumed first, so every attempt needs a fresh challenge.
    nonce_ok = state.security.take_challenge(payload.nonce, payload.device_id)
    device = await devices.active_device(session, payload.device_id)
    if (
        not nonce_ok
        or device is None
        or not verify_signature(device.public_key, auth_message(device.id, payload.nonce), payload.signature)
    ):
        logger.warning("device_login_failed", device_id=payload.device_id)
        raise HTTPException(status_code=401, detail=_LOGIN_FAILED)
    await devices.touch(session, device)
    access_token, ttl = state.security.new_session(device.id, device.is_admin)
    return TokenOut(token=access_token, expires_in=ttl, device_id=device.id, is_admin=device.is_admin)


class MeOut(BaseModel):
    mode: str
    server_name: str
    device_id: int | None = None
    device_name: str | None = None
    is_admin: bool


@router.get("/me", response_model=MeOut, dependencies=[Depends(require_auth)])
async def me(
    request: Request, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> MeOut:
    """Who the caller is; also how the UI tells desktop from server mode."""
    current = getattr(request.state, "session", None)
    if current is None:
        return MeOut(mode=state.settings.mode, server_name=state.settings.server_name, is_admin=True)
    device = await session.get(Device, current.device_id)
    return MeOut(
        mode="server",
        server_name=state.settings.server_name,
        device_id=current.device_id,
        device_name=device.name if device else None,
        is_admin=current.is_admin,
    )


class DeviceOut(BaseModel):
    id: int
    name: str
    fingerprint: str
    is_admin: bool
    created_at: dt.datetime
    last_seen_at: dt.datetime | None
    revoked: bool


@devices_router.get("", response_model=list[DeviceOut], dependencies=[Depends(require_admin)])
async def list_devices(session: AsyncSession = Depends(get_db)) -> list[DeviceOut]:
    rows = (await session.execute(select(Device).order_by(Device.created_at))).scalars()
    return [
        DeviceOut(
            id=d.id,
            name=d.name,
            fingerprint=devices.fingerprint(d.public_key),
            is_admin=d.is_admin,
            created_at=d.created_at,
            last_seen_at=d.last_seen_at,
            revoked=d.revoked_at is not None,
        )
        for d in rows
    ]


@devices_router.delete("/{device_id}", status_code=204, dependencies=[Depends(require_admin)])
async def revoke_device(
    device_id: int, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> None:
    """Revokes a device (e.g. a lost phone): it is logged out at once and
    can't log in again. Allowed from the internet too -- it only takes
    access away."""
    device = await devices.active_device(session, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    if device.is_admin:
        admins = (
            await session.execute(select(Device.id).where(Device.is_admin.is_(True), Device.revoked_at.is_(None)))
        ).all()
        if len(admins) <= 1:
            raise HTTPException(status_code=409, detail="Das letzte Admin-Gerät kann nicht widerrufen werden")
    device.revoked_at = dt.datetime.now(dt.UTC)
    await session.commit()
    state.security.end_sessions(device_id)
    logger.info("device_revoked", device_id=device_id, name=device.name)


