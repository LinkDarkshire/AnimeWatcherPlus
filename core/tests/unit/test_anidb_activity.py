from __future__ import annotations

import time

import httpx
import pytest
import respx

from app.config import Settings
from app.providers.anidb import ANIDB_HTTP_API, AniDBProvider
from app.providers.anidb_activity import anidb_status, anidb_subject
from app.services.anidb_watch import AniDBBlockWatcher
from app.services.jobs import EventBus, JobQueue
from tests.unit.test_anidb_provider import SAMPLE_ANIME_XML


def _provider(tmp_path, **overrides) -> tuple[AniDBProvider, list[tuple[str, str | None]]]:
    settings = Settings(data_dir=tmp_path, anidb_min_interval_s=0.0, **overrides)
    provider = AniDBProvider(settings, http_client=httpx.AsyncClient())
    seen: list[tuple[str, str | None]] = []

    async def record() -> None:
        seen.append((provider.activity.state, provider.activity.detail))

    provider.activity.subscribe(record)
    return provider, seen


@pytest.mark.asyncio
@respx.mock
async def test_real_requests_report_activity_with_the_anime_name(tmp_path) -> None:
    respx.get(ANIDB_HTTP_API).mock(return_value=httpx.Response(200, text=SAMPLE_ANIME_XML))
    provider, seen = _provider(tmp_path)

    with anidb_subject("Crest of the Stars"):
        await provider.fetch("1")
    assert seen == [("requesting", "Crest of the Stars (#1)"), ("idle", None)]

    seen.clear()
    await provider.fetch("1")  # answered from the local cache: no request, no activity
    assert seen == []
    assert anidb_status(provider, None)["requests_today"] == 1


def test_blocked_reports_ban_daily_cap_and_pause(tmp_path) -> None:
    provider, _ = _provider(tmp_path, anidb_daily_cap=2)
    assert provider.blocked() == (None, None)

    provider._banned_until = time.time() + 600
    assert provider.blocked()[0] == "ban"
    provider._banned_until = 0.0

    provider.limiter._call_day = time.strftime("%Y-%m-%d")
    provider.limiter._call_count = 2
    reason, until = provider.blocked()
    assert reason == "daily_cap" and until > time.time()
    provider.limiter._call_count = 0

    for _ in range(provider.circuit_breaker.failure_threshold):
        provider.circuit_breaker.record_failure()
    assert provider.blocked()[0] == "paused"


@pytest.mark.asyncio
async def test_watcher_requeues_work_once_a_ban_ends(tmp_path) -> None:
    provider, seen = _provider(tmp_path)
    provider._banned_until = time.time() + 600
    calls: list[str] = []

    async def resume_anime() -> int:
        calls.append("anime")
        return 3

    async def resume_wishlist() -> int:
        calls.append("wishlist")
        return 1

    watcher = AniDBBlockWatcher(provider, [resume_anime, resume_wishlist])
    assert await watcher.check() == 0  # still banned
    assert calls == []

    provider._banned_until = time.time() - 1  # ban over
    assert await watcher.check() == 4
    assert calls == ["anime", "wishlist"]
    assert provider.activity.resumed_at is not None
    assert seen  # the UI was told

    assert await watcher.check() == 0  # only once per block


def test_status_counts_queued_anidb_jobs(tmp_path) -> None:
    provider, _ = _provider(tmp_path)
    queue = JobQueue(EventBus())

    async def nothing() -> None:
        return None

    queue.enqueue("identify", nothing)
    queue.enqueue("wishlist_details", nothing)
    queue.enqueue("scan", nothing)  # not AniDB work

    status = anidb_status(provider, queue)
    assert status["queued_jobs"] == 2
    assert status["state"] == "idle" and status["blocked_reason"] is None
