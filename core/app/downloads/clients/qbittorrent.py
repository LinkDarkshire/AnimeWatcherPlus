from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.downloads.base import DownloadClient, DownloadClientError, DownloadStatus, SettingField

_QB_ETA_INFINITE = 8640000  # qBittorrent's "no estimate"


def _qbittorrent_status(torrent: dict[str, Any]) -> DownloadStatus:
    state = str(torrent.get("state") or "")
    progress = float(torrent.get("progress") or 0.0)
    eta = torrent.get("eta")
    eta_seconds = int(eta) if isinstance(eta, int) and 0 <= eta < _QB_ETA_INFINITE else None
    speed = int(torrent.get("dlspeed") or 0) or None
    if state in ("error", "missingFiles"):
        return DownloadStatus("error", progress, message="Fehler" if state == "error" else "Dateien fehlen")
    if progress >= 1.0:
        seeding = state in ("uploading", "stalledUP", "forcedUP", "queuedUP")
        return DownloadStatus("seeding" if seeding else "finished", 1.0)
    if state in ("pausedDL", "stoppedDL"):
        return DownloadStatus("paused", progress)
    if state in ("queuedDL", "checkingDL", "checkingResumeData", "allocating", "moving"):
        return DownloadStatus("queued", progress)
    if state == "metaDL":
        return DownloadStatus("downloading", progress, speed, eta_seconds, "Lädt Torrent-Metadaten")
    if state == "stalledDL":
        return DownloadStatus("downloading", progress, speed, eta_seconds, "Keine Verbindung zu Peers")
    return DownloadStatus("downloading", progress, speed, eta_seconds)


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

    async def add(self, link: str, *, destination: str | None, package_name: str) -> str | None:
        await self._login()
        # qBittorrent doesn't answer with the torrent's hash, so each download
        # gets its own tag to find it again for the progress display.
        tag = f"awp-{uuid.uuid4().hex[:12]}"
        fields: dict[str, str] = {"urls": link, "tags": tag}
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
        return tag

    async def status(self, handles: list[str]) -> dict[str, DownloadStatus]:
        await self._login()
        found: dict[str, DownloadStatus] = {}
        for tag in handles:
            response = await self._request("GET", "/api/v2/torrents/info", params={"tag": tag})
            if response.status_code != 200:
                raise DownloadClientError(f"qBittorrent antwortet mit HTTP {response.status_code}")
            torrents = response.json()
            if torrents:
                found[tag] = _qbittorrent_status(torrents[0])
        return found

    async def remove(self, handles: list[str]) -> None:
        """Removes the finished torrents from qBittorrent's list, keeping the files."""
        await self._login()
        hashes: list[str] = []
        for tag in handles:
            response = await self._request("GET", "/api/v2/torrents/info", params={"tag": tag})
            if response.status_code == 200:
                hashes += [str(t["hash"]) for t in response.json() if t.get("hash")]
        if hashes:
            response = await self._request(
                "POST", "/api/v2/torrents/delete", data={"hashes": "|".join(hashes), "deleteFiles": "false"}
            )
            if response.status_code != 200:
                raise DownloadClientError(f"qBittorrent antwortet mit HTTP {response.status_code}")

    async def close(self) -> None:
        await self._http.aclose()
