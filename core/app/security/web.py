"""Logins of the web interface (server mode): a browser logs in with user
name and password and gets a session cookie. The cookie is HttpOnly (page
scripts can't read it), Secure and SameSite=Strict (other sites can't make
the browser send it); requests that change something must also carry the
WEB_HEADER, which a foreign page can't add without the server's consent."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebAccount, WebSession

COOKIE_NAME = "awp_session"
WEB_HEADER = "x-awp-web"
SESSION_TTL = dt.timedelta(days=30)

# Failed logins: per user name, and for everyone together (behind a reverse
# proxy all browsers share one address, so there's no per-address limit).
FAILURE_WINDOW_S = 15 * 60
MAX_FAILURES_PER_NAME = 5
MAX_FAILURES_TOTAL = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_username(username: str) -> str:
    return username.strip().casefold()


async def create_session(session: AsyncSession, account: WebAccount) -> str:
    token = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.UTC)
    await session.execute(delete(WebSession).where(WebSession.expires_at <= now))
    session.add(WebSession(token_hash=_hash_token(token), account_id=account.id, expires_at=now + SESSION_TTL))
    account.last_login_at = now
    await session.commit()
    return token


async def account_for_token(session: AsyncSession, token: str) -> WebAccount | None:
    row = await session.scalar(select(WebSession).where(WebSession.token_hash == _hash_token(token)))
    if row is None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=dt.UTC)
    if expires <= dt.datetime.now(dt.UTC):
        return None
    return await session.get(WebAccount, row.account_id)


async def end_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(WebSession).where(WebSession.token_hash == _hash_token(token)))
    await session.commit()


async def end_sessions(session: AsyncSession, account_id: int) -> None:
    """Logs an account out in every browser (password changed, deleted)."""
    await session.execute(delete(WebSession).where(WebSession.account_id == account_id))
    await session.commit()


@dataclass
class LoginThrottle:
    """Slows down password guessing: after too many failures, logins for
    that name (or for everyone) wait until the oldest failure is old enough."""

    by_name: dict[str, deque[float]] = field(default_factory=dict)
    total: deque[float] = field(default_factory=deque)

    @staticmethod
    def _trim(failures: deque[float], now: float) -> None:
        while failures and failures[0] <= now - FAILURE_WINDOW_S:
            failures.popleft()

    def wait_s(self, username: str) -> int:
        """Seconds until a login for this name is allowed again (0: now)."""
        now = time.time()
        self._trim(self.total, now)
        waits = [0.0]
        if len(self.total) >= MAX_FAILURES_TOTAL:
            waits.append(self.total[0] + FAILURE_WINDOW_S - now)
        failures = self.by_name.get(username)
        if failures is not None:
            self._trim(failures, now)
            if len(failures) >= MAX_FAILURES_PER_NAME:
                waits.append(failures[0] + FAILURE_WINDOW_S - now)
        return int(max(waits) + 0.999)

    def failed(self, username: str) -> None:
        now = time.time()
        self.total.append(now)
        self.by_name.setdefault(username, deque()).append(now)
        if len(self.by_name) > 1000:
            # Many made-up names: forget those without recent failures.
            for name in [n for n, f in self.by_name.items() if not f or f[-1] <= now - FAILURE_WINDOW_S]:
                del self.by_name[name]

    def succeeded(self, username: str) -> None:
        self.by_name.pop(username, None)
