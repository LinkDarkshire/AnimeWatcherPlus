"""Example of your own search source (SearchSource).

Installation: copy this file into the app's plugins folder (shown on the
download page under "Einrichtung", e.g. ~/.local/share/AnimeWatcherPlus/plugins
or %APPDATA%\\AnimeWatcherPlus\\plugins) and restart the app.

This source searches a plain text file with one link per line:

    Title | Episode | Link
    Frieren | 3 | https://example.org/frieren-03.mkv
    Frieren | | magnet:?xt=urn:btih:...        <- no episode: the whole series

For a source that asks a website or an API, only `search` needs to work
differently (httpx is already part of the app). For websites with a search
page, website_template.py does most of the work for you.
"""

from __future__ import annotations

from pathlib import Path

from app.downloads import SearchQuery, SearchResult, SearchSource, SearchSourceError, SettingField


class LinkListSource(SearchSource):
    # Unique id. Don't change it later -- saved setups refer to it.
    id = "example_link_list"
    name = "Linkliste (Textdatei)"
    description = "Sucht Links in einer eigenen Textdatei (Titel | Folge | Link)."

    # The settings the app asks for when this source is set up. Types: text,
    # password, number, bool, path. The values end up in self.config.
    settings_schema = (
        SettingField("file", "Pfad zur Textdatei", type="path", required=True),
    )

    def _lines(self) -> list[tuple[str, str, str]]:
        path = Path(self.config["file"])
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            # The message of a PluginError is shown to the user as is.
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
        # query.titles: every known name of the anime, the preferred one first.
        # query.episode: the episode number, or None for the whole series.
        wanted_titles = {t.casefold() for t in query.titles}
        wanted_episode = "" if query.episode is None else str(query.episode)
        return [
            SearchResult(title=f"{title} {episode}".strip(), link=link)
            for title, episode, link in self._lines()
            if title.casefold() in wanted_titles and episode.lstrip("0") == wanted_episode.lstrip("0")
        ]
