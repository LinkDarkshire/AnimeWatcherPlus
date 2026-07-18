from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod

import structlog

from app.domain.metadata import AnimeMetadata, ProviderManifest, SearchHit

logger = structlog.get_logger(__name__)


class ProviderBannedError(Exception):
    """Raised when a provider signals a ban/hard-block (e.g. AniDB <error>banned</error>)."""


class MetadataProvider(ABC):
    manifest: ProviderManifest

    @abstractmethod
    async def search(self, title: str, year: int | None) -> list[SearchHit]: ...

    @abstractmethod
    async def fetch(self, external_id: str) -> AnimeMetadata | None: ...

    async def map_from_anidb(self, anidb_id: int) -> str | None:  # optional
        return None

    async def get_full_info(self, external_id: str) -> dict | None:  # optional
        """Everything the provider knows about this anime, beyond the lean
        AnimeMetadata contract -- used for the aniinfo.json sidecar. Providers
        that don't support this (most will not) simply return None.
        """
        return None


class RateLimiter:
    """Enforces a minimum interval between calls plus a hard daily cap.

    NFA-04: >=2s between AniDB HTTP requests, configurable daily ceiling. In-memory
    only for this MVP pass (resets on process restart) — persisting the daily
    counter across restarts is deferred to M9/M10 hardening.
    """

    def __init__(self, min_interval_s: float, daily_cap: int | None = None) -> None:
        self.min_interval_s = min_interval_s
        self.daily_cap = daily_cap
        self._last_call = 0.0
        self._lock = asyncio.Lock()
        self._call_day: str | None = None
        self._call_count = 0

    async def acquire(self) -> None:
        async with self._lock:
            today = time.strftime("%Y-%m-%d")
            if self._call_day != today:
                self._call_day = today
                self._call_count = 0
            if self.daily_cap is not None and self._call_count >= self.daily_cap:
                raise ProviderBannedError("daily call cap reached")

            now = time.monotonic()
            wait = self.min_interval_s - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            self._call_count += 1


class CircuitBreaker:
    """After N failures, stays open for `cooldown_s` so a dead provider doesn't
    stall the identification pipeline (Kap. 9.2).
    """

    def __init__(self, failure_threshold: int = 5, cooldown_s: float = 600.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_s:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            logger.warning("circuit_breaker_opened", cooldown_s=self.cooldown_s)


class ProviderRegistry:
    """Holds the configurable Primär/Sekundär/Tertiär provider chain (FA-06).

    Only AniDB is registered in this MVP pass; Jikan/TMDB (FA-25) plug into the
    same chain in M9 without touching this class.
    """

    def __init__(self) -> None:
        self._chain: list[MetadataProvider] = []

    def register(self, provider: MetadataProvider) -> None:
        self._chain.append(provider)

    @property
    def chain(self) -> list[MetadataProvider]:
        return list(self._chain)

    def get_provider(self, plugin_id: str) -> MetadataProvider | None:
        for provider in self._chain:
            if provider.manifest.plugin_id == plugin_id:
                return provider
        return None

    async def fetch_chain(self, external_ids: dict[str, str]) -> tuple[AnimeMetadata | None, str | None]:
        """Tries each provider in order using its matching external id; returns the
        first successful result plus the provider name that produced it.
        """
        for provider in self._chain:
            ext_id = external_ids.get(provider.manifest.plugin_id)
            if not ext_id:
                continue
            try:
                metadata = await provider.fetch(ext_id)
            except ProviderBannedError:
                logger.warning("provider_banned_skipping", provider=provider.manifest.plugin_id)
                continue
            except Exception:
                logger.exception("provider_fetch_failed", provider=provider.manifest.plugin_id)
                continue
            if metadata is not None:
                return metadata, provider.manifest.plugin_id
        return None, None
