"""Server mode: is there a newer release than the one running? Admin devices
show a hint with how to update the container. The server never updates
itself -- that would need access to the Docker socket, i.e. root on the
host."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import structlog

from app import __version__

logger = structlog.get_logger(__name__)

CACHE_S = 6 * 3600


def parse_version(value: str) -> tuple[int, ...]:
    """'v0.3.10' -> (0, 3, 10); anything after the numbers is ignored."""
    parts: list[int] = []
    for part in value.strip().lstrip("vV").split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


@dataclass
class ReleaseInfo:
    current: str
    latest: str | None
    update_available: bool
    url: str | None


class ReleaseChecker:
    def __init__(self, repo: str, client: httpx.AsyncClient | None = None) -> None:
        self._repo = repo
        self._client = client
        self._cached: tuple[float, str | None, str | None] | None = None

    async def _fetch(self) -> tuple[str | None, str | None]:
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.get(
                f"https://api.github.com/repos/{self._repo}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("tag_name") or "").lstrip("vV") or None, data.get("html_url")
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("release_check_failed", error=str(exc))
            return None, None
        finally:
            if self._client is None:
                await client.aclose()

    async def info(self) -> ReleaseInfo:
        now = time.monotonic()
        if self._cached is None or now - self._cached[0] > CACHE_S:
            latest, url = await self._fetch()
            self._cached = (now, latest, url)
        _, latest, url = self._cached
        newer = latest is not None and parse_version(latest) > parse_version(__version__)
        return ReleaseInfo(current=__version__, latest=latest, update_available=newer, url=url)
