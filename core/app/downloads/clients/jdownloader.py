from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from app.downloads.base import DownloadClient, DownloadClientError, SettingField

_LINE_BREAKS = re.compile(r"[\r\n]+")


class JDownloaderClient(DownloadClient):
    """JDownloader 2 via its "Folder Watch" extension: every link becomes a
    small .crawljob file in a watched folder, which JDownloader picks up on
    its own. Needs no API access and no MyJDownloader account -- only the
    extension (Settings -> Extensions -> Folder Watch) and a folder both
    this app and JDownloader can reach."""

    id = "jdownloader"
    name = "JDownloader 2"
    description = "Übergibt Direkt-Links über die Ordnerüberwachung (Folder Watch) an JDownloader."
    settings_schema = (
        SettingField(
            "watch_folder",
            "Überwachter Ordner",
            type="path",
            required=True,
            help=(
                "Der Ordner, den die JDownloader-Erweiterung \"Folder Watch\" beobachtet "
                "(Standard: der Unterordner \"folderwatch\" im JDownloader-Verzeichnis)."
            ),
        ),
        SettingField(
            "download_path",
            "Download-Pfad aus Sicht von JDownloader",
            type="path",
            help=(
                "Nur nötig, wenn JDownloader auf einem anderen Rechner läuft und den Download-Ordner "
                "unter einem anderen Pfad sieht. Leer: der Pfad des Download-Ordners."
            ),
        ),
        SettingField("auto_start", "Download sofort starten", type="bool", default=True),
    )

    def accepts(self, link: str) -> bool:
        # JDownloader handles hoster and direct links, but not torrents.
        return link.lower().startswith(("http://", "https://"))

    def _watch_folder(self) -> Path:
        folder = Path(str(self.config.get("watch_folder") or ""))
        if not str(folder) or not folder.is_dir():
            raise DownloadClientError(f"Überwachter Ordner nicht gefunden: {folder}")
        return folder

    async def test_connection(self) -> None:
        folder = self._watch_folder()
        probe = folder / f".awp-write-test-{uuid.uuid4().hex}"
        try:
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise DownloadClientError(f"Kein Schreibzugriff auf {folder}: {exc}") from exc

    async def add(self, link: str, *, destination: str | None, package_name: str) -> None:
        folder = self._watch_folder()
        flag = "TRUE" if self.config.get("auto_start") else "FALSE"
        lines = {
            "text": link,
            "packageName": package_name,
            "enabled": "TRUE",
            "autoConfirm": flag,
            "autoStart": flag,
        }
        target = self.config.get("download_path") or destination
        if target:
            lines["downloadFolder"] = target
        # One value per line: a stray line break would start a new key.
        content = "".join(f"{key}={_LINE_BREAKS.sub(' ', str(value))}\n" for key, value in lines.items())

        name = f"awp-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        # Written under a name JDownloader ignores, then renamed: it must
        # never pick up a half-written file.
        temp = folder / f".{name}.tmp"
        try:
            temp.write_text(content, encoding="utf-8")
            temp.replace(folder / f"{name}.crawljob")
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise DownloadClientError(f"Crawljob konnte nicht geschrieben werden: {exc}") from exc
