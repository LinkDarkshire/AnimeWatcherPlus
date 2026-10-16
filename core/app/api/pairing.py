from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.auth import require_admin
from app.security import devices
from app.security.keys import InvalidKey, normalize_public_key
from app.security.store import JOIN_REQUEST_TTL_S
from app.state import AppState

logger = structlog.get_logger(__name__)

# Served only on the LAN-only pairing port (see PortSeparationMiddleware):
# a device can only get access while it is in the server's local network.
router = APIRouter(prefix="/pair", tags=["pairing"])


class PairInfo(BaseModel):
    server_name: str
    version: str
    setup_required: bool


class NewDevice(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    public_key: str


class SetupIn(NewDevice):
    code: str


class PairedOut(BaseModel):
    device_id: int
    is_admin: bool


class CodeOut(BaseModel):
    code: str
    expires_in: int


class JoinIn(NewDevice):
    code: str


class JoinOut(BaseModel):
    request_id: str
    fingerprint: str
    expires_in: int


class JoinStatus(BaseModel):
    status: Literal["pending", "approved", "rejected"]
    device_id: int | None


class PendingRequest(BaseModel):
    id: str
    name: str
    fingerprint: str


class Decision(BaseModel):
    approve: bool
    admin: bool = False


async def _checked_key(session: AsyncSession, public_key: str) -> str:
    try:
        key = normalize_public_key(public_key)
    except InvalidKey as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if await devices.key_in_use(session, key):
        raise HTTPException(status_code=409, detail="Dieser Schlüssel ist bereits gekoppelt")
    return key


@router.get("/info", response_model=PairInfo)
async def info(session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)) -> PairInfo:
    from app import __version__

    return PairInfo(
        server_name=state.settings.server_name,
        version=__version__,
        setup_required=not await devices.has_active_admin(session),
    )


@router.post("/setup", response_model=PairedOut)
async def setup(
    payload: SetupIn, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> PairedOut:
    """Pairs the first device -- the admin -- with the one-time setup code
    the server prints to its log on start."""
    if await devices.has_active_admin(session):
        raise HTTPException(status_code=409, detail="Der Server ist bereits eingerichtet")
    key = await _checked_key(session, payload.public_key)
    if not state.security.use_setup_code(payload.code):
        logger.warning("setup_code_rejected")
        raise HTTPException(status_code=401, detail="Einrichtungscode falsch oder abgelaufen")
    device = await devices.create_device(session, payload.name.strip(), key, is_admin=True)
    logger.info("admin_device_paired", device_id=device.id, name=device.name)
    return PairedOut(device_id=device.id, is_admin=True)


@router.post("/codes", response_model=CodeOut, dependencies=[Depends(require_admin)])
async def new_pairing_code(state: AppState = Depends(get_app_state)) -> CodeOut:
    """A one-time code (5 minutes) for adding another device, shown by an
    admin device as text and QR code."""
    code, ttl = state.security.new_pairing_code()
    return CodeOut(code=code, expires_in=ttl)


@router.post("/join", response_model=JoinOut)
async def join(
    payload: JoinIn, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> JoinOut:
    """A new device asks to be paired. Needs a current pairing code, and an
    admin still has to approve it."""
    key = await _checked_key(session, payload.public_key)
    if not state.security.use_pairing_code(payload.code):
        logger.warning("pairing_code_rejected", name=payload.name)
        raise HTTPException(status_code=401, detail="Kopplungscode falsch oder abgelaufen")
    request = state.security.new_join_request(payload.name.strip(), key)
    logger.info("pairing_requested", name=request.name)
    return JoinOut(request_id=request.id, fingerprint=devices.fingerprint(key), expires_in=JOIN_REQUEST_TTL_S)


@router.get("/join/{request_id}", response_model=JoinStatus)
async def join_status(request_id: str, state: AppState = Depends(get_app_state)) -> JoinStatus:
    """Polled by the joining device until an admin decided."""
    request = state.security.join_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden oder abgelaufen")
    return JoinStatus(status=request.status, device_id=request.device_id)


@router.get("/requests", response_model=list[PendingRequest], dependencies=[Depends(require_admin)])
async def pending_requests(state: AppState = Depends(get_app_state)) -> list[PendingRequest]:
    state.security.purge()
    return [
        PendingRequest(id=r.id, name=r.name, fingerprint=devices.fingerprint(r.public_key))
        for r in state.security.join_requests.values()
        if r.status == "pending"
    ]


@router.post("/requests/{request_id}", response_model=JoinStatus, dependencies=[Depends(require_admin)])
async def decide(
    request_id: str,
    payload: Decision,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> JoinStatus:
    request = state.security.join_request(request_id)
    if request is None or request.status != "pending":
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden oder abgelaufen")
    if payload.approve:
        if await devices.key_in_use(session, request.public_key):
            raise HTTPException(status_code=409, detail="Dieser Schlüssel ist bereits gekoppelt")
        device = await devices.create_device(session, request.name, request.public_key, is_admin=payload.admin)
        request.status, request.device_id = "approved", device.id
        logger.info("device_paired", device_id=device.id, name=device.name, admin=payload.admin)
    else:
        request.status = "rejected"
        logger.info("pairing_rejected", name=request.name)
    return JoinStatus(status=request.status, device_id=request.device_id)
