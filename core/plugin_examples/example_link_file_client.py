"""Example of your own download client (DownloadClient).

Installation as for example_link_list.py: copy it into the app's plugins
folder and restart the app.

This "client" doesn't download anything itself; it appends every link to a
text file -- e.g. for a downloader that works through such a list. A real
client would call the program's API in `add` instead (see
app/downloads/clients/ in the source code).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.downloads import DownloadClient, DownloadClientError, SettingField


class LinkFileClient(DownloadClient):
    id = "example_link_file"
    name = "Linkdatei"
    description = "Schreibt jeden Link als Zeile in eine Textdatei."
    settings_schema = (
        SettingField("file", "Zieldatei", type="path", required=True),
    )

    def accepts(self, link: str) -> bool:
        # Which links this client can take; the app refuses to send it others.
        return True

    async def add(self, link: str, *, destination: str | None, package_name: str) -> str | None:
        # destination: the app's download folder (where the scanner looks).
        # package_name: a readable name, e.g. "Frieren - 03".
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        try:
            with Path(self.config["file"]).open("a", encoding="utf-8") as f:
                f.write(f"{stamp}\t{package_name}\t{destination or ''}\t{link}\n")
        except OSError as exc:
            raise DownloadClientError(f"Zieldatei nicht beschreibbar: {exc}") from exc
        # Returning None: this client can't report progress later.
        return None
