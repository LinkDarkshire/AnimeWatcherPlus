from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx

from app.downloads import DownloadClientError
from app.downloads.clients.myjdownloader import (
    API_URL,
    MyJDownloaderClient,
    _secret,
    decrypt,
    encrypt,
)

EMAIL, PASSWORD = "User@Example.org", "hunter2"
SESSION = "ab" * 32


class FakeMyJD:
    """Speaks the server side of the protocol: checks every signature and
    encrypts/decrypts with the tokens the real service derives."""

    def __init__(self, devices: list[dict], auth_ok: bool = True) -> None:
        self.devices = devices
        self.auth_ok = auth_ok
        self.login = _secret(EMAIL, PASSWORD, "server")
        session = bytes.fromhex(SESSION)
        self.server_token = hashlib.sha256(self.login + session).digest()
        self.device_token = hashlib.sha256(_secret(EMAIL, PASSWORD, "device") + session).digest()
        self.calls: list[tuple[str, list]] = []
        self.disconnected = False

    def _check_signature(self, request: httpx.Request, key: bytes) -> dict[str, str]:
        parts = urlsplit(str(request.url))
        signed, _, signature = f"{parts.path}?{parts.query}".rpartition("&signature=")
        assert hmac.new(key, signed.encode(), hashlib.sha256).hexdigest() == signature
        return dict(parse_qsl(parts.query))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/my/connect":
            params = self._check_signature(request, self.login)
            assert params["email"] == EMAIL and params["appkey"] == "AnimeWatcherPlus"
            if not self.auth_ok:
                return httpx.Response(403, json={"src": "MYJD", "type": "AUTH_FAILED"})
            body = {"sessiontoken": SESSION, "regaintoken": "cd" * 32, "rid": int(params["rid"])}
            return httpx.Response(200, text=encrypt(self.login, json.dumps(body)))
        if path in ("/my/listdevices", "/my/disconnect"):
            params = self._check_signature(request, self.server_token)
            assert params["sessiontoken"] == SESSION
            self.disconnected |= path == "/my/disconnect"
            body = {"list": self.devices, "rid": int(params["rid"])}
            return httpx.Response(200, text=encrypt(self.server_token, json.dumps(body)))
        if path.startswith(f"/t_{SESSION}_"):
            assert request.headers["content-type"].startswith("application/aesjson-jd")
            payload = json.loads(decrypt(self.device_token, request.content.decode()))
            device_id = path.split("/")[1].rsplit("_", 1)[1]
            self.calls.append((device_id, [json.loads(p) for p in payload["params"]]))
            body = {"data": None, "rid": payload["rid"]}
            return httpx.Response(200, text=encrypt(self.device_token, json.dumps(body)))
        raise AssertionError(f"unexpected request {path}")


def _client(**config) -> MyJDownloaderClient:
    return MyJDownloaderClient({"email": EMAIL, "password": PASSWORD, **config})


def test_encrypt_roundtrip() -> None:
    token = bytes(range(32))
    assert decrypt(token, encrypt(token, '{"ä": 1}')) == '{"ä": 1}'


@pytest.mark.asyncio
@respx.mock
async def test_add_links_to_the_only_device() -> None:
    server = FakeMyJD(devices=[{"id": "dev1", "name": "JD Docker", "type": "jd"}])
    respx.route(url__startswith=API_URL).mock(side_effect=server.handle)

    client = _client(download_path="/output", auto_start=True)
    await client.add("https://host/ep.mkv", destination="/downloads", package_name="Show - 01")

    [(device_id, [query])] = server.calls
    assert device_id == "dev1"
    assert query["links"] == "https://host/ep.mkv"
    assert query["packageName"] == "Show - 01"
    assert query["destinationFolder"] == "/output"  # container path wins over the app's
    assert query["autostart"] is True
    assert server.disconnected


@pytest.mark.asyncio
@respx.mock
async def test_device_selection() -> None:
    devices = [{"id": "a", "name": "PC"}, {"id": "b", "name": "NAS"}]
    server = FakeMyJD(devices=devices)
    respx.route(url__startswith=API_URL).mock(side_effect=server.handle)

    with pytest.raises(DownloadClientError, match="Mehrere Geräte"):
        await _client().test_connection()
    with pytest.raises(DownloadClientError, match="nicht gefunden"):
        await _client(device="Laptop").test_connection()

    await _client(device="nas").add("https://x/y", destination=None, package_name="X")
    assert server.calls[-1][0] == "b"
    assert "destinationFolder" not in server.calls[-1][1][0]


@pytest.mark.asyncio
@respx.mock
async def test_wrong_password_is_reported() -> None:
    respx.route(url__startswith=API_URL).mock(side_effect=FakeMyJD(devices=[], auth_ok=False).handle)

    with pytest.raises(DownloadClientError, match="Anmeldung fehlgeschlagen"):
        await _client().test_connection()


def test_accepts_only_http_links() -> None:
    client = _client()
    assert client.accepts("https://host/file")
    assert not client.accepts("magnet:?xt=urn:btih:1")
