from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from app.downloads import DownloadClientError
from app.downloads.clients.transmission import TransmissionClient

RPC = "http://192.168.1.10:9091/transmission/rpc"


def _rpc_server(calls: list[dict], *, result: str = "success", require_auth: str | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        if require_auth is not None:
            expected = "Basic " + base64.b64encode(require_auth.encode()).decode()
            if request.headers.get("authorization") != expected:
                return httpx.Response(401)
        if request.headers.get("x-transmission-session-id") != "sess-1":
            return httpx.Response(409, headers={"X-Transmission-Session-Id": "sess-1"})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"result": result, "arguments": {}})

    return handle


@pytest.mark.asyncio
@respx.mock
async def test_add_does_session_handshake_and_uses_container_path() -> None:
    calls: list[dict] = []
    respx.post(RPC).mock(side_effect=_rpc_server(calls, require_auth="admin:secret"))

    client = TransmissionClient(
        {"host": "192.168.1.10", "username": "admin", "password": "secret", "download_path": "/downloads"}
    )
    await client.test_connection()
    await client.add("magnet:?xt=urn:btih:abc", destination="Z:\\Downloads", package_name="Show - 01")
    await client.close()

    assert [c["method"] for c in calls] == ["session-get", "torrent-add"]
    added = calls[1]["arguments"]
    assert added == {"filename": "magnet:?xt=urn:btih:abc", "paused": False, "download-dir": "/downloads"}


@pytest.mark.asyncio
@respx.mock
async def test_full_address_and_app_destination() -> None:
    calls: list[dict] = []
    respx.post("https://nas.local:9091/transmission/rpc").mock(side_effect=_rpc_server(calls))

    client = TransmissionClient({"host": "https://nas.local:9091", "auto_start": False})
    await client.add("https://x/t.torrent", destination="/mnt/downloads", package_name="Show")

    assert calls[0]["arguments"] == {"filename": "https://x/t.torrent", "paused": True, "download-dir": "/mnt/downloads"}


@pytest.mark.asyncio
@respx.mock
async def test_errors_are_readable() -> None:
    respx.post(RPC).mock(side_effect=_rpc_server([], require_auth="admin:secret"))
    with pytest.raises(DownloadClientError, match="Anmeldung"):
        await TransmissionClient({"host": "192.168.1.10", "username": "admin", "password": "wrong"}).test_connection()

    respx.post("http://10.0.0.2:9091/transmission/rpc").mock(
        side_effect=_rpc_server([], result="invalid or corrupt torrent file")
    )
    with pytest.raises(DownloadClientError, match="corrupt"):
        await TransmissionClient({"host": "10.0.0.2"}).add("https://x/y", destination=None, package_name="X")

    respx.post("http://10.0.0.3:9091/transmission/rpc").mock(return_value=httpx.Response(403))
    with pytest.raises(DownloadClientError, match="whitelist"):
        await TransmissionClient({"host": "10.0.0.3"}).test_connection()


@pytest.mark.asyncio
@respx.mock
async def test_add_returns_hash_and_status_maps_states() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.headers.get("x-transmission-session-id") != "s":
            return httpx.Response(409, headers={"X-Transmission-Session-Id": "s"})
        body = json.loads(request.content)
        if body["method"] == "torrent-add":
            return httpx.Response(200, json={"result": "success", "arguments": {"torrent-duplicate": {"hashString": "abc"}}})
        assert body["arguments"]["ids"] == ["abc", "def", "gone"]
        torrents = [
            {"hashString": "abc", "status": 4, "percentDone": 0.25, "rateDownload": 1000, "eta": 60, "error": 0},
            {"hashString": "def", "status": 6, "percentDone": 1.0, "rateDownload": 0, "eta": -1, "error": 0},
        ]
        return httpx.Response(200, json={"result": "success", "arguments": {"torrents": torrents}})

    respx.post(RPC).mock(side_effect=handle)
    client = TransmissionClient({"host": "192.168.1.10"})

    assert await client.add("magnet:?xt=1", destination=None, package_name="X") == "abc"
    statuses = await client.status(["abc", "def", "gone"])
    assert (statuses["abc"].state, statuses["abc"].progress, statuses["abc"].eta_seconds) == ("downloading", 0.25, 60)
    assert statuses["def"].state == "seeding"
    assert "gone" not in statuses
