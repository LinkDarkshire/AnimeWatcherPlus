"""Beispiel für einen eigenen Download-Client (DownloadClient).

Installation wie bei beispiel_linkliste.py: in den Plugin-Ordner der App
kopieren und die App neu starten.

Dieser "Client" lädt nichts selbst herunter, sondern hängt jeden Link an
eine Textdatei an -- z. B. für einen Downloader, der eine solche Liste
abarbeitet. Ein echter Client würde in `add` stattdessen die API des
Programms aufrufen (siehe app/downloads/clients/ im Quellcode).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.downloads import DownloadClient, DownloadClientError, SettingField


class LinkFileClient(DownloadClient):
    id = "beispiel_linkdatei"
    name = "Linkdatei"
    description = "Schreibt jeden Link als Zeile in eine Textdatei."
    settings_schema = (
        SettingField("file", "Zieldatei", type="path", required=True),
    )

    def accepts(self, link: str) -> bool:
        # Welche Links dieser Client annimmt -- die App bietet ihn nur dafür an.
        return True

    async def add(self, link: str, *, destination: str | None, package_name: str) -> None:
        # destination: der Download-Ordner der App (dort sucht der Scanner).
        # package_name: lesbarer Name, z. B. "Frieren - 03".
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        try:
            with Path(self.config["file"]).open("a", encoding="utf-8") as f:
                f.write(f"{stamp}\t{package_name}\t{destination or ''}\t{link}\n")
        except OSError as exc:
            raise DownloadClientError(f"Zieldatei nicht beschreibbar: {exc}") from exc
