"""Passwords of the web interface's accounts: stored only as a salted,
deliberately slow scrypt hash, compared in constant time."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import cache

# ~0.1 s and 32 MiB per check: unnoticeable at a login, expensive for anyone
# guessing against a stolen database.
_N = 2**15
_R = 8
_P = 1
_MAXMEM = 64 * 1024 * 1024
MIN_LENGTH = 8
MAX_LENGTH = 256


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=32)


def hash_password(password: str) -> str:
    """"scrypt$n$r$p$salt$hash" -- the parameters travel with the hash, so
    they can be raised later without breaking existing accounts."""
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, _N, _R, _P)
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@cache
def dummy_hash() -> str:
    """Checked against when the user name doesn't exist, so a login takes
    as long either way and doesn't reveal which names exist."""
    return hash_password(secrets.token_urlsafe(16))
