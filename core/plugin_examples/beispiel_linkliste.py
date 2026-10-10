"""Beispiel für eine eigene Such-Quelle (SearchSource).

Installation: diese Datei in den Plugin-Ordner der App kopieren (wird auf
der Download-Seite unter "Einrichtung" angezeigt, z. B.
~/.local/share/AnimeWatcherPlus/plugins oder
%APPDATA%\\AnimeWatcherPlus\\plugins) und die App neu starten.

Diese Quelle durchsucht eine einfache Textdatei, eine Zeile pro Link:

    Titel | Folge | Link
    Frieren | 3 | https://example.org/frieren-03.mkv
    Frieren | | magnet:?xt=urn:btih:...        <- leere Folge: ganze Serie

Für eine Quelle, die eine Webseite oder API abfragt, nur `search` anders
implementieren (z. B. mit httpx, das in der App bereits enthalten ist).
"""

from __future__ import annotations

from pathlib import Path

from app.downloads import SearchQuery, SearchResult, SearchSource, SearchSourceError, SettingField


class LinkListSource(SearchSource):
    # Eindeutige ID -- darf sich später nicht mehr ändern, die eingerichteten
    # Einträge verweisen darauf.
    id = "beispiel_linkliste"
    name = "Linkliste (Textdatei)"
    description = "Sucht Links in einer eigenen Textdatei (Titel | Folge | Link)."

    # Diese Felder fragt die App beim Einrichten ab. Typen: text, password,
    # number, bool, path. Die Werte stehen danach in self.config.
    settings_schema = (
        SettingField("file", "Pfad zur Textdatei", type="path", required=True),
    )

    def _lines(self) -> list[tuple[str, str, str]]:
        path = Path(self.config["file"])
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            # PluginError-Meldungen werden dem Benutzer so angezeigt.
            raise SearchSourceError(f"Linkliste nicht lesbar: {exc}") from exc
        rows = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3 and parts[2]:
                rows.append((parts[0], parts[1], parts[2]))
        return rows

    async def test_connection(self) -> None:
        self._lines()

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        # query.titles: alle bekannten Namen des Animes, bevorzugter zuerst.
        # query.episode: Folgennummer, oder None für die ganze Serie.
        wanted_titles = {t.casefold() for t in query.titles}
        wanted_episode = "" if query.episode is None else str(query.episode)
        return [
            SearchResult(title=f"{title} {episode}".strip(), link=link)
            for title, episode, link in self._lines()
            if title.casefold() in wanted_titles and episode.lstrip("0") == wanted_episode.lstrip("0")
        ]
