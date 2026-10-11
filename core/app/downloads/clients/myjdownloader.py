from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.downloads.base import DownloadClient, DownloadClientError, DownloadStatus, SettingField

API_URL = "https://api.jdownloader.org"
# Identifies this application to the MyJDownloader service.
APP_KEY = "AnimeWatcherPlus"

_ERROR_MESSAGES = {
    "AUTH_FAILED": "MyJDownloader-Anmeldung fehlgeschlagen (E-Mail/Passwort?)",
    "EMAIL_INVALID": "MyJDownloader: E-Mail-Adresse ungültig",
    "EMAIL_FORBIDDEN": "MyJDownloader: E-Mail-Adresse nicht bestätigt",
    "TOO_MANY_REQUESTS": "MyJDownloader: zu viele Anfragen, bitte später erneut versuchen",
    "OFFLINE": "JDownloader ist gerade nicht mit MyJDownloader verbunden",
    "TOKEN_INVALID": "MyJDownloader-Sitzung abgelaufen",
    "MAINTENANCE": "MyJDownloader ist gerade in Wartung",
    "OVERLOAD": "MyJDownloader ist gerade überlastet",
}


def _secret(email: str, password: str, domain: str) -> bytes:
    return hashlib.sha256(f"{email.lower()}{password}{domain}".encode()).digest()


def _aes(token: bytes) -> Cipher:
    # First half of the 32-byte token is the IV, second half the AES-128 key.
    return Cipher(algorithms.AES(token[16:]), modes.CBC(token[:16]))


def encrypt(token: bytes, plaintext: str) -> str:
    padder = padding.PKCS7(128).padder()
    data = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = _aes(token).encryptor()
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()


def decrypt(token: bytes, ciphertext: str) -> str:
    decryptor = _aes(token).decryptor()
    data = decryptor.update(base64.b64decode(ciphertext)) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(data) + unpadder.finalize()).decode()


def _sign(key: bytes, data: str) -> str:
    return hmac.new(key, data.encode(), hashlib.sha256).hexdigest()


class _Session:
    """One MyJDownloader login: the request signing and the AES layer the
    API wraps around every call (protocol as implemented by JDownloader's
    own web interface and the `myjdapi` library)."""

    def __init__(self, http: httpx.AsyncClient, email: str, password: str) -> None:
        self._http = http
        self._email = email
        self._login_secret = _secret(email, password, "server")
        self._device_secret = _secret(email, password, "device")
        self._session_token: str | None = None
        self._server_token: bytes | None = None
        self._device_token: bytes | None = None
        self._rid = 0

    def _next_rid(self) -> int:
        # Must increase with every request; milliseconds as the API expects.
        self._rid = max(self._rid + 1, int(time.time() * 1000))
        return self._rid

    def _error(self, response: httpx.Response, token: bytes | None) -> DownloadClientError:
        error_type = None
        for attempt in (lambda: json.loads(response.text), lambda: json.loads(decrypt(token, response.text))):
            try:
                error_type = attempt().get("type")
                break
            except Exception:  # noqa: BLE001 - try the next way to read it
                continue
        message = _ERROR_MESSAGES.get(error_type or "", f"MyJDownloader antwortet mit HTTP {response.status_code}")
        return DownloadClientError(message + (f" ({error_type})" if error_type and error_type not in _ERROR_MESSAGES else ""))

    async def _get(self, path: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        key = self._server_token or self._login_secret
        query = path + "?" + "&".join([f"{k}={quote(v)}" for k, v in params] + [f"rid={self._next_rid()}"])
        url = f"{API_URL}{query}&signature={_sign(key, query)}"
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"MyJDownloader nicht erreichbar: {exc}") from exc
        if response.status_code != 200:
            raise self._error(response, key)
        return json.loads(decrypt(key, response.text))

    async def connect(self) -> None:
        data = await self._get("/my/connect", [("email", self._email), ("appkey", APP_KEY)])
        self._session_token = data["sessiontoken"]
        session = bytes.fromhex(self._session_token)
        self._server_token = hashlib.sha256(self._login_secret + session).digest()
        self._device_token = hashlib.sha256(self._device_secret + session).digest()

    async def disconnect(self) -> None:
        if self._session_token is None:
            return
        try:
            await self._get("/my/disconnect", [("sessiontoken", self._session_token)])
        except DownloadClientError:
            pass  # the session times out on its own anyway
        self._session_token = None

    async def list_devices(self) -> list[dict[str, Any]]:
        assert self._session_token is not None
        data = await self._get("/my/listdevices", [("sessiontoken", self._session_token)])
        return list(data.get("list") or [])

    async def call(self, device_id: str, path: str, params: list[Any]) -> Any:
        """Calls an API method on the JDownloader instance itself."""
        assert self._session_token is not None and self._device_token is not None
        rid = self._next_rid()
        body = json.dumps({"apiVer": 1, "url": path, "params": [json.dumps(p) for p in params], "rid": rid})
        url = f"{API_URL}/t_{self._session_token}_{quote(device_id)}{path}"
        try:
            response = await self._http.post(
                url,
                content=encrypt(self._device_token, body),
                headers={"Content-Type": "application/aesjson-jd; charset=utf-8"},
            )
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"MyJDownloader nicht erreichbar: {exc}") from exc
        if response.status_code != 200:
            raise self._error(response, self._device_token)
        return json.loads(decrypt(self._device_token, response.text)).get("data")


def _jd_status(package: dict[str, Any]) -> DownloadStatus:
    total = int(package.get("bytesTotal") or 0)
    loaded = int(package.get("bytesLoaded") or 0)
    progress = loaded / total if total > 0 else None
    message = package.get("status") or None
    if package.get("finished"):
        return DownloadStatus("finished", 1.0, message=message)
    if package.get("running"):
        eta = package.get("eta")
        return DownloadStatus(
            "downloading",
            progress,
            int(package.get("speed") or 0) or None,
            int(eta) if isinstance(eta, int) and eta >= 0 else None,
            message,
        )
    return DownloadStatus("queued", progress, message=message)


class MyJDownloaderClient(DownloadClient):
    """JDownloader 2 via the MyJDownloader service. Works wherever
    JDownloader runs -- a Docker container, the NAS, another PC -- as long as
    it is signed in to the same MyJDownloader account; no shared folder and
    no open port needed."""

    id = "myjdownloader"
    name = "JDownloader 2 (MyJDownloader)"
    description = "Übergibt Direkt-Links über dein MyJDownloader-Konto an JDownloader."
    settings_schema = (
        SettingField("email", "MyJDownloader-E-Mail", required=True),
        SettingField("password", "MyJDownloader-Passwort", type="password", required=True),
        SettingField(
            "device",
            "Gerätename",
            help="Name der JDownloader-Instanz in MyJDownloader. Leer: das einzige verbundene Gerät.",
        ),
        SettingField(
            "download_path",
            "Download-Pfad aus Sicht von JDownloader",
            type="path",
            help=(
                "Bei JDownloader im Container: der Pfad, unter dem der Container den Download-Ordner "
                "sieht (z. B. /output). Leer: der Pfad des Download-Ordners der App."
            ),
        ),
        SettingField("auto_start", "Download sofort starten", type="bool", default=True),
    )

    def __init__(self, config: dict[str, Any], http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._http = http_client or httpx.AsyncClient(timeout=20.0)

    def accepts(self, link: str) -> bool:
        return link.lower().startswith(("http://", "https://"))

    async def _with_device(self, session: _Session) -> str:
        devices = await session.list_devices()
        wanted = (self.config.get("device") or "").strip()
        if wanted:
            for device in devices:
                if str(device.get("name", "")).casefold() == wanted.casefold():
                    return str(device["id"])
            names = ", ".join(str(d.get("name")) for d in devices) or "keine"
            raise DownloadClientError(f"Gerät \"{wanted}\" nicht gefunden (verbunden: {names})")
        if len(devices) == 1:
            return str(devices[0]["id"])
        if not devices:
            raise DownloadClientError("Kein JDownloader mit diesem MyJDownloader-Konto verbunden")
        names = ", ".join(str(d.get("name")) for d in devices)
        raise DownloadClientError(f"Mehrere Geräte verbunden ({names}) -- bitte einen Gerätenamen eintragen")

    async def _session(self) -> _Session:
        session = _Session(self._http, str(self.config["email"]), str(self.config["password"]))
        await session.connect()
        return session

    async def test_connection(self) -> None:
        session = await self._session()
        try:
            await self._with_device(session)
        finally:
            await session.disconnect()

    async def add(self, link: str, *, destination: str | None, package_name: str) -> str | None:
        session = await self._session()
        try:
            device_id = await self._with_device(session)
            query: dict[str, Any] = {
                "links": link,
                "packageName": package_name,
                "autostart": bool(self.config.get("auto_start")),
                "overwritePackagizerRules": True,
            }
            target = self.config.get("download_path") or destination
            if target:
                query["destinationFolder"] = target
            await session.call(device_id, "/linkgrabberv2/addLinks", [query])
        finally:
            await session.disconnect()
        # JDownloader keeps the package name (overwritePackagizerRules), so
        # it finds the download again for the progress display.
        return package_name

    async def status(self, handles: list[str]) -> dict[str, DownloadStatus]:
        session = await self._session()
        try:
            device_id = await self._with_device(session)
            downloads = await session.call(
                device_id,
                "/downloadsV2/queryPackages",
                [
                    {
                        "bytesLoaded": True,
                        "bytesTotal": True,
                        "finished": True,
                        "running": True,
                        "speed": True,
                        "eta": True,
                        "status": True,
                        "maxResults": -1,
                        "startAt": 0,
                    }
                ],
            )
            grabbed = await session.call(
                device_id, "/linkgrabberv2/queryPackages", [{"maxResults": -1, "startAt": 0}]
            )
        finally:
            await session.disconnect()

        by_name = {str(p.get("name")): p for p in downloads or []}
        waiting = {str(p.get("name")) for p in grabbed or []}
        found: dict[str, DownloadStatus] = {}
        for name in handles:
            package = by_name.get(name)
            if package is not None:
                found[name] = _jd_status(package)
            elif name in waiting:
                found[name] = DownloadStatus("queued", message="Wartet im Linkgrabber auf Bestätigung")
        return found

    async def close(self) -> None:
        await self._http.aclose()
