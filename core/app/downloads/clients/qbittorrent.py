from __future__ import annotations

from typing import Any

import httpx

from app.downloads.base import DownloadClient, DownloadClientError, SettingField


class QBittorrentClient(DownloadClient):
    """qBittorrent via its Web UI API (v2). The Web UI has to be enabled in
    qBittorrent: Tools -> Options -> Web UI."""

    id = "qbittorrent"
    name = "qBittorrent"
    description = "Übergibt Magnet-Links und .torrent-URLs an die qBittorrent Web UI."
    settings_schema = (
        SettingField("url", "Web-UI-Adresse", default="http://127.0.0.1:8080", required=True),
        SettingField(
            "username",
            "Benutzername",
            help="Leer lassen, wenn qBittorrent für lokale Zugriffe keine Anmeldung verlangt.",
        ),
        SettingField("password", "Passwort", type="password"),
        SettingField("category", "Kategorie", help="Optional, z. B. \"anime\"."),
        SettingField(
            "save_path",
            "Speicherpfad aus Sicht von qBittorrent",
            type="path",
            help=(
                "Nur nötig, wenn qBittorrent auf einem anderen Rechner (z. B. dem NAS) läuft und "
                "den Download-Ordner unter einem anderen Pfad sieht. Leer: der Pfad des Download-Ordners."
            ),
        ),
    )

    def __init__(self, config: dict[str, Any], http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._http = http_client or httpx.AsyncClient(timeout=15.0)
        self._logged_in = False

    @property
    def _base(self) -> str:
        return str(self.config["url"]).rstrip("/")

    def accepts(self, link: str) -> bool:
        # Any http(s) URL, not just ones ending in .torrent: indexers serve
        # torrent files from URLs like ".../download.php?id=123".
        return link.lower().startswith(("magnet:", "http://", "https://"))

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, f"{self._base}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"qBittorrent nicht erreichbar ({self._base}): {exc}") from exc

    async def _login(self) -> None:
        if self._logged_in or not self.config.get("username"):
            return
        response = await self._request(
            "POST",
            "/api/v2/auth/login",
            data={"username": self.config["username"], "password": self.config.get("password") or ""},
        )
        if response.status_code == 403:
            raise DownloadClientError("qBittorrent hat diese IP nach zu vielen Fehlversuchen gesperrt")
        if response.status_code != 200 or response.text.strip() != "Ok.":
            raise DownloadClientError("qBittorrent-Anmeldung fehlgeschlagen (Benutzername/Passwort?)")
        self._logged_in = True

    async def test_connection(self) -> None:
        await self._login()
        response = await self._request("GET", "/api/v2/app/version")
        if response.status_code == 403:
            raise DownloadClientError("qBittorrent verlangt eine Anmeldung")
        if response.status_code != 200:
            raise DownloadClientError(f"qBittorrent antwortet mit HTTP {response.status_code}")

    async def add(self, link: str, *, destination: str | None, package_name: str) -> None:
        await self._login()
        fields: dict[str, str] = {"urls": link}
        save_path = self.config.get("save_path") or destination
        if save_path:
            fields["savepath"] = save_path
        if self.config.get("category"):
            fields["category"] = self.config["category"]
        # The API expects multipart/form-data; (None, value) makes httpx send
        # plain form fields that way.
        response = await self._request(
            "POST", "/api/v2/torrents/add", files={k: (None, v) for k, v in fields.items()}
        )
        if response.status_code == 403:
            raise DownloadClientError("qBittorrent verlangt eine Anmeldung")
        if response.status_code != 200 or response.text.strip() == "Fails.":
            raise DownloadClientError(f"qBittorrent hat den Link abgelehnt (HTTP {response.status_code})")

    async def close(self) -> None:
        await self._http.aclose()
