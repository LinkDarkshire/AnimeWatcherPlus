from __future__ import annotations

from typing import Any

import httpx

from app.downloads.base import DownloadClient, DownloadClientError, SettingField

_SESSION_HEADER = "X-Transmission-Session-Id"


class TransmissionClient(DownloadClient):
    """Transmission via its RPC interface -- the usual way to reach it in a
    container (e.g. linuxserver/transmission), where it listens on port 9091."""

    id = "transmission"
    name = "Transmission"
    description = "Übergibt Magnet-Links und .torrent-URLs an Transmission (RPC)."
    settings_schema = (
        SettingField(
            "host",
            "IP-Adresse oder Hostname",
            required=True,
            help="z. B. 192.168.1.10 -- oder eine vollständige Adresse wie https://nas.local:9091",
        ),
        SettingField("port", "Port", type="number", default=9091),
        SettingField("username", "Benutzername", help="Nur, wenn in Transmission eine Anmeldung aktiviert ist."),
        SettingField("password", "Passwort", type="password"),
        SettingField(
            "download_path",
            "Download-Pfad aus Sicht von Transmission",
            type="path",
            help=(
                "Bei Transmission im Container: der Pfad, unter dem der Container den Download-Ordner "
                "sieht (z. B. /downloads). Leer: der Pfad des Download-Ordners der App."
            ),
        ),
        SettingField("auto_start", "Download sofort starten", type="bool", default=True),
    )

    def __init__(self, config: dict[str, Any], http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        auth = None
        if self.config.get("username"):
            auth = httpx.BasicAuth(str(self.config["username"]), str(self.config.get("password") or ""))
        self._http = http_client or httpx.AsyncClient(timeout=15.0)
        self._auth = auth
        self._session_id: str | None = None

    @property
    def _url(self) -> str:
        host = str(self.config["host"]).strip().rstrip("/")
        if "://" not in host:
            host = f"http://{host}:{int(self.config.get('port') or 9091)}"
        # A full address may already include the RPC path.
        return host if host.endswith("/transmission/rpc") else f"{host}/transmission/rpc"

    def accepts(self, link: str) -> bool:
        return link.lower().startswith(("magnet:", "http://", "https://"))

    async def _rpc(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"method": method, "arguments": arguments or {}}
        # Transmission's CSRF protection: the first request (or one after a
        # restart) is answered with 409 and the session id to send instead.
        for _ in range(2):
            headers = {_SESSION_HEADER: self._session_id} if self._session_id else {}
            try:
                response = await self._http.post(self._url, json=payload, headers=headers, auth=self._auth)
            except httpx.HTTPError as exc:
                raise DownloadClientError(f"Transmission nicht erreichbar ({self._url}): {exc}") from exc
            if response.status_code == 409 and _SESSION_HEADER in response.headers:
                self._session_id = response.headers[_SESSION_HEADER]
                continue
            break
        if response.status_code == 401:
            raise DownloadClientError("Transmission-Anmeldung fehlgeschlagen (Benutzername/Passwort?)")
        if response.status_code == 403:
            raise DownloadClientError(
                "Transmission lehnt den Zugriff ab -- steht die IP dieser App in der rpc-whitelist?"
            )
        if response.status_code != 200:
            raise DownloadClientError(f"Transmission antwortet mit HTTP {response.status_code}")
        body = response.json()
        if body.get("result") != "success":
            raise DownloadClientError(f"Transmission: {body.get('result')}")
        return body.get("arguments") or {}

    async def test_connection(self) -> None:
        await self._rpc("session-get", {"fields": ["version"]})

    async def add(self, link: str, *, destination: str | None, package_name: str) -> None:
        arguments: dict[str, Any] = {"filename": link, "paused": not self.config.get("auto_start")}
        target = self.config.get("download_path") or destination
        if target:
            arguments["download-dir"] = target
        # "torrent-duplicate" is fine too: it's already there.
        await self._rpc("torrent-add", arguments)

    async def close(self) -> None:
        await self._http.aclose()
