"""Plugin API for downloads.

Two kinds of plugin classes, both discovered the same way (built in, or as a
``.py`` file in the ``plugins`` folder of the app's data directory):

* ``DownloadClient`` -- something a link can be handed to (qBittorrent,
  JDownloader, ...). The client downloads into the app's download folder,
  where the scanner picks the files up and the sorter files them away.
* ``SearchSource`` -- something that can be asked for links to an episode
  or a series (an indexer, a site, a local list, ...).

A plugin class declares an ``id``, a display ``name`` and the settings it
needs (``settings_schema``). The user can then set up any number of
configured instances of it in the UI; each instance gets its values as the
``config`` dict passed to ``__init__``.

Everything a plugin needs is importable from ``app.downloads``::

    from app.downloads import DownloadClient, SettingField, DownloadClientError

This module is the contract external plugins are written against -- keep it
backwards compatible.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

SettingType = Literal["text", "password", "number", "bool", "path"]


@dataclass(frozen=True)
class SettingField:
    """One setting a plugin asks the user for. ``password`` values are never
    sent back to the UI once stored."""

    key: str
    label: str
    type: SettingType = "text"
    default: Any = None
    required: bool = False
    help: str | None = None


class PluginError(Exception):
    """Raised by a plugin for an expected failure (unreachable, wrong
    credentials, rejected link). The message is shown to the user as is."""


class DownloadClientError(PluginError):
    pass


class SearchSourceError(PluginError):
    pass


class NothingFound(SearchSourceError):
    """Raise instead of returning an empty list to tell the user *why*
    nothing turned up (e.g. which search terms were tried). Shown as a note,
    not as an error."""


class _Plugin(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    # A list or a tuple -- plugins may use either.
    settings_schema: ClassVar[Sequence[SettingField]] = ()

    def __init__(self, config: dict[str, Any]) -> None:
        # Defaults first, so a plugin can read every declared key without
        # checking for its presence.
        self.config: dict[str, Any] = {f.key: f.default for f in self.settings_schema}
        self.config.update({k: v for k, v in config.items() if v is not None})

    async def test_connection(self) -> None:  # noqa: B027 - optional hook, empty by default
        """Checks that the configured instance works. Raise a PluginError
        with a helpful message if it doesn't. Optional."""

    async def close(self) -> None:  # noqa: B027 - optional hook, empty by default
        """Releases resources (HTTP clients, ...). Optional."""


class DownloadClient(_Plugin):
    """Receives links and downloads them."""

    @abstractmethod
    def accepts(self, link: str) -> bool:
        """Whether this client can handle the link at all (e.g. only
        ``magnet:`` and ``.torrent`` for a torrent client). The UI only
        offers clients that accept the link."""

    @abstractmethod
    async def add(self, link: str, *, destination: str | None, package_name: str) -> str | None:
        """Hands the link over. ``destination`` is the download folder the
        files should end up in (``None``: the client's own default).
        ``package_name`` is a readable name for the download (anime title +
        episode) for clients that group downloads. Raise
        DownloadClientError on failure.

        May return a handle (torrent hash, tag, package name, ...) by which
        ``status`` finds this download later; None if the client can't
        report progress."""

    async def status(self, handles: list[str]) -> dict[str, DownloadStatus]:
        """Progress of the downloads behind these handles (from ``add``).
        Handles the client doesn't know (any more) can simply be left out.
        Optional -- without it the app shows the download as "unknown"."""
        return {}

    async def remove(self, handles: list[str]) -> None:
        """Removes these finished downloads from the client's own list, to
        keep it tidy -- never their files. Optional; only ever called for
        downloads ``status`` reported as finished."""


DownloadState = Literal["queued", "downloading", "paused", "seeding", "finished", "error", "unknown"]


@dataclass
class DownloadStatus:
    state: DownloadState
    progress: float | None = None  # 0.0 .. 1.0
    speed_bps: int | None = None  # bytes per second
    eta_seconds: int | None = None
    message: str | None = None  # anything worth showing ("Entpacken", an error text, ...)


@dataclass(frozen=True)
class SearchQuery:
    """What to look for. ``titles`` holds every known name of the anime,
    the preferred one first -- release names use all of them."""

    titles: list[str]
    anidb_id: int | None = None
    episode: int | None = None  # None: the whole series (wishlist)


# Words that often stand in a title on one site and are missing on another.
DEFAULT_STRIP_WORDS: tuple[str, ...] = ("OVA", "ONA", "The Animation")

_EDGE_PUNCTUATION = " -–—:;,.·!?()[]"  # noqa: RUF001 - dashes are meant literally


def _strip_words(title: str, words: Sequence[str]) -> str:
    for word in words:
        title = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\(\s*\)|\[\s*\]", " ", title)  # brackets left empty
    return " ".join(title.split()).strip(_EDGE_PUNCTUATION)


def fallback_search_terms(
    titles: Sequence[str], *, strip_words: Sequence[str] = DEFAULT_STRIP_WORDS, max_titles: int = 3
) -> list[str]:
    """Search terms from most to least specific, for sites that know a series
    under a shorter name than AniDB:

    1. the titles as they are ("OVA Tensura Nikki"),
    2. the same without words like "OVA" / "The Animation" ("Tensura Nikki"),
    3. the first word of each of those ("Tensura").

    Each term only once, empty ones dropped."""
    full = [t.strip() for t in titles[:max_titles] if t and t.strip()]
    stripped = [_strip_words(t, strip_words) for t in full]
    first_words = [s.split()[0].strip(_EDGE_PUNCTUATION) for s in stripped if s.split()]
    return [term for term in dict.fromkeys([*full, *stripped, *first_words]) if term]


@dataclass
class SearchResult:
    """One link the user can pick. Only `title` and `link` are required;
    everything else is shown when present."""

    title: str
    link: str
    size_bytes: int | None = None
    seeders: int | None = None
    published: str | None = None  # ISO date/time, if the source has one
    info_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # Which hoster/mirror the link points to ("MEGA", "1fichier", ...).
    hoster: str | None = None
    # "stream" links are shown, but never handed to a download client.
    kind: Literal["download", "stream"] = "download"
    # Display details as label -> value ("Sprache": "Subbed", "Format": "MKV").
    details: dict[str, str] = field(default_factory=dict)
    # The link leads to an intermediate page (URL shortener, captcha, ...)
    # rather than the file: the app opens it in the browser and lets the user
    # paste the final link instead of sending this one to a client.
    needs_browser: bool = False


@dataclass
class SeriesHit:
    """A series page found by a two-stage source's first step. `extra` is
    passed back unchanged to `list_releases`, for anything the source needs
    to remember (an internal id, ...); it must be JSON-serializable."""

    title: str
    url: str
    extra: dict[str, Any] = field(default_factory=dict)


class SearchSource(_Plugin):
    """Finds links for an episode or a series."""

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Returns matching links, best first. Raise SearchSourceError on
        failure; return an empty list when there simply are no results."""


class TwoStageSearchSource(SearchSource):
    """For sites where you first find the series page and then pick an
    episode/variant on it. The app shows the series hits, the user picks one
    (or it's taken automatically when there is exactly one), then the
    releases of that page are listed."""

    @abstractmethod
    async def search_series(self, query: SearchQuery) -> list[SeriesHit]:
        """Step 1: the series pages matching the query."""

    @abstractmethod
    async def list_releases(self, series: SeriesHit, query: SearchQuery) -> list[SearchResult]:
        """Step 2: the links on that series page -- for `query.episode` only,
        or for every episode when it is None."""

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """One-step use (as any SearchSource): only when the series is
        unambiguous."""
        hits = await self.search_series(query)
        return await self.list_releases(hits[0], query) if len(hits) == 1 else []
