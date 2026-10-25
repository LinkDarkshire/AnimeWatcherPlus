from __future__ import annotations

import httpx
import pytest

from app import __version__
from app.services.server_release import ReleaseChecker, parse_version


def test_versions_compare_by_number() -> None:
    assert parse_version("v0.3.10") > parse_version("0.3.9")
    assert parse_version("0.4.0") > parse_version("0.3.99")
    assert parse_version("1.0.0-beta") == (1, 0, 0)


@pytest.mark.asyncio
async def test_newer_release_is_reported_and_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"tag_name": "v99.0.0", "html_url": "https://example/r"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checker = ReleaseChecker("owner/repo", client)
        info = await checker.info()
        await checker.info()

    assert (info.current, info.latest, info.update_available) == (__version__, "99.0.0", True)
    assert calls == ["https://api.github.com/repos/owner/repo/releases/latest"]


@pytest.mark.asyncio
async def test_unreachable_github_is_no_update() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        info = await ReleaseChecker("owner/repo", client).info()
    assert (info.latest, info.update_available) == (None, False)
