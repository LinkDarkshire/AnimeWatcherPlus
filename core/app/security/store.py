from __future__ import annotations

import hmac
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

# Short-lived secrets live in memory only. A restart drops them all: devices
# simply log in again, and pending pairings have to be started over.
TOKEN_TTL_S = 15 * 60
CHALLENGE_TTL_S = 60
PAIRING_CODE_TTL_S = 5 * 60
JOIN_REQUEST_TTL_S = 10 * 60
MAX_CODE_ATTEMPTS = 5

# No 0/O, 1/I/L: codes are read off a screen and typed in.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_code(length: int) -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
    return "-".join(raw[i : i + 4] for i in range(0, length, 4))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def codes_match(given: str, expected: str) -> bool:
    return hmac.compare_digest(normalize_code(given).encode(), normalize_code(expected).encode())


@dataclass
class Session:
    device_id: int
    is_admin: bool
    expires_at: float


@dataclass
class OneTimeCode:
    code: str
    expires_at: float | None  # None: until used (the first-device setup code)
    attempts_left: int = MAX_CODE_ATTEMPTS


@dataclass
class JoinRequest:
    id: str
    name: str
    public_key: str
    expires_at: float
    status: Literal["pending", "approved", "rejected"] = "pending"
    device_id: int | None = None


@dataclass
class SecurityState:
    """Everything short-lived the server-mode auth needs."""

    sessions: dict[str, Session] = field(default_factory=dict)
    challenges: dict[str, tuple[int, float]] = field(default_factory=dict)
    setup_code: OneTimeCode | None = None
    pairing_codes: list[OneTimeCode] = field(default_factory=list)
    join_requests: dict[str, JoinRequest] = field(default_factory=dict)

    def purge(self) -> None:
        now = time.time()
        self.sessions = {t: s for t, s in self.sessions.items() if s.expires_at > now}
        self.challenges = {n: c for n, c in self.challenges.items() if c[1] > now}
        self.pairing_codes = [c for c in self.pairing_codes if c.expires_at is None or c.expires_at > now]
        self.join_requests = {i: r for i, r in self.join_requests.items() if r.expires_at > now}

    # --- login -----------------------------------------------------------------

    def new_challenge(self, device_id: int) -> str:
        self.purge()
        nonce = secrets.token_urlsafe(32)
        self.challenges[nonce] = (device_id, time.time() + CHALLENGE_TTL_S)
        return nonce

    def take_challenge(self, nonce: str, device_id: int) -> bool:
        """Single use: a nonce is gone after the first attempt, right or wrong."""
        self.purge()
        entry = self.challenges.pop(nonce, None)
        return entry is not None and entry[0] == device_id

    def new_session(self, device_id: int, is_admin: bool) -> tuple[str, int]:
        self.purge()
        token = secrets.token_urlsafe(32)
        self.sessions[token] = Session(device_id, is_admin, time.time() + TOKEN_TTL_S)
        return token, TOKEN_TTL_S

    def session(self, token: str) -> Session | None:
        session = self.sessions.get(token)
        if session is None or session.expires_at <= time.time():
            return None
        return session

    def end_sessions(self, device_id: int) -> None:
        """Logs a device out everywhere, e.g. when it is revoked."""
        self.sessions = {t: s for t, s in self.sessions.items() if s.device_id != device_id}

    # --- pairing ------------------------------------------------------------------

    def new_setup_code(self) -> str:
        code = new_code(12)
        self.setup_code = OneTimeCode(code, expires_at=None)
        return code

    def use_setup_code(self, given: str) -> bool:
        """The setup code works once. After too many wrong tries it's gone,
        and a new one only appears with a server restart."""
        code = self.setup_code
        if code is None:
            return False
        if codes_match(given, code.code):
            self.setup_code = None
            return True
        code.attempts_left -= 1
        if code.attempts_left <= 0:
            self.setup_code = None
        return False

    def new_pairing_code(self) -> tuple[str, int]:
        self.purge()
        code = OneTimeCode(new_code(8), time.time() + PAIRING_CODE_TTL_S)
        self.pairing_codes.append(code)
        return code.code, PAIRING_CODE_TTL_S

    def use_pairing_code(self, given: str) -> bool:
        self.purge()
        for code in list(self.pairing_codes):
            if codes_match(given, code.code):
                self.pairing_codes.remove(code)  # single use
                return True
        # A wrong guess costs every open code an attempt: guessing is useless.
        for code in list(self.pairing_codes):
            code.attempts_left -= 1
            if code.attempts_left <= 0:
                self.pairing_codes.remove(code)
        return False

    def new_join_request(self, name: str, public_key: str) -> JoinRequest:
        self.purge()
        request = JoinRequest(uuid.uuid4().hex, name, public_key, time.time() + JOIN_REQUEST_TTL_S)
        self.join_requests[request.id] = request
        return request

    def join_request(self, request_id: str) -> JoinRequest | None:
        self.purge()
        return self.join_requests.get(request_id)
