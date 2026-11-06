"""The web interface's logins (server mode): log in and out with user name
and password, and the accounts admins manage for it."""

from __future__ import annotations

import asyncio
import datetime as dt

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.auth import require_admin, require_auth, same_origin
from app.db.models import WebAccount
from app.security import passwords, web
from app.state import AppState

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/web", tags=["web"])

_LOGIN_FAILED = "Benutzername oder Passwort falsch"


def _server_only(state: AppState) -> None:
    if state.settings.mode != "server":
        raise HTTPException(status_code=404, detail="Nur im Server-Modus")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        web.COOKIE_NAME,
        token,
        max_age=int(web.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


Username = Field(min_length=1, max_length=64)
Password = Field(min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=passwords.MAX_LENGTH)


@router.post("/login", status_code=204)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> None:
    _server_only(state)
    if not same_origin(request.headers):
        raise HTTPException(status_code=403, detail="Anmeldung nur über die Weboberfläche")
    name = web.normalize_username(payload.username)
    wait = state.login_throttle.wait_s(name)
    if wait:
        raise HTTPException(status_code=429, detail=f"Zu viele Fehlversuche, bitte in {(wait + 59) // 60} Min. erneut versuchen")
    account = await session.scalar(select(WebAccount).where(WebAccount.username == name))
    stored = account.password_hash if account else passwords.dummy_hash()
    if not await asyncio.to_thread(passwords.verify_password, payload.password, stored) or account is None:
        state.login_throttle.failed(name)
        logger.warning("web_login_failed", username=name)
        raise HTTPException(status_code=401, detail=_LOGIN_FAILED)
    state.login_throttle.succeeded(name)
    token = await web.create_session(session, account)
    _set_session_cookie(response, token)
    logger.info("web_login", username=name)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_db)) -> None:
    token = request.cookies.get(web.COOKIE_NAME)
    if token and same_origin(request.headers):
        await web.end_session(session, token)
    response.delete_cookie(web.COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=passwords.MAX_LENGTH)
    new_password: str = Password


@router.put("/password", status_code=204, dependencies=[Depends(require_auth)])
async def change_own_password(
    payload: PasswordChangeIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> None:
    """A web account changes its own password; all its other browsers are
    logged out, this one gets a fresh session."""
    current = getattr(request.state, "session", None)
    account = await session.get(WebAccount, current.account_id) if current and current.account_id else None
    if account is None:
        raise HTTPException(status_code=400, detail="Nur für Web-Zugänge")
    if not await asyncio.to_thread(passwords.verify_password, payload.current_password, account.password_hash):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort falsch")
    account.password_hash = await asyncio.to_thread(passwords.hash_password, payload.new_password)
    await session.commit()
    await web.end_sessions(session, account.id)
    token = await web.create_session(session, account)
    _set_session_cookie(response, token)


# --- accounts (admins) ---------------------------------------------------------------


class AccountOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class AccountIn(BaseModel):
    username: str = Username
    password: str = Password
    is_admin: bool = False


class AccountPatch(BaseModel):
    password: str | None = Field(default=None, min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH)
    is_admin: bool | None = None


def _out(account: WebAccount) -> AccountOut:
    return AccountOut(
        id=account.id,
        username=account.username,
        is_admin=account.is_admin,
        created_at=account.created_at,
        last_login_at=account.last_login_at,
    )


@router.get("/accounts", response_model=list[AccountOut], dependencies=[Depends(require_admin)])
async def list_accounts(session: AsyncSession = Depends(get_db)) -> list[AccountOut]:
    rows = (await session.execute(select(WebAccount).order_by(WebAccount.username))).scalars()
    return [_out(a) for a in rows]


@router.post("/accounts", response_model=AccountOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_account(
    payload: AccountIn, session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> AccountOut:
    _server_only(state)
    name = web.normalize_username(payload.username)
    if not name or any(ch.isspace() for ch in name):
        raise HTTPException(status_code=422, detail="Benutzername ohne Leerzeichen angeben")
    account = WebAccount(
        username=name,
        password_hash=await asyncio.to_thread(passwords.hash_password, payload.password),
        is_admin=payload.is_admin,
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Diesen Benutzernamen gibt es schon") from None
    await session.refresh(account)
    logger.info("web_account_created", username=name, is_admin=account.is_admin)
    return _out(account)


@router.patch("/accounts/{account_id}", response_model=AccountOut, dependencies=[Depends(require_admin)])
async def update_account(account_id: int, payload: AccountPatch, session: AsyncSession = Depends(get_db)) -> AccountOut:
    """New password (logs the account out everywhere) or admin rights."""
    account = await session.get(WebAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden")
    if payload.is_admin is not None:
        account.is_admin = payload.is_admin
    if payload.password is not None:
        account.password_hash = await asyncio.to_thread(passwords.hash_password, payload.password)
    await session.commit()
    if payload.password is not None:
        await web.end_sessions(session, account.id)
    return _out(account)


@router.delete("/accounts/{account_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_account(account_id: int, session: AsyncSession = Depends(get_db)) -> None:
    account = await session.get(WebAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden")
    await web.end_sessions(session, account.id)
    await session.delete(account)
    await session.commit()
    logger.info("web_account_deleted", username=account.username)
