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

    async def test_connection(self) -> None:
        """Checks that the configured instance works. Raise a PluginError
        with a helpful message if it doesn't. Optional."""

    async def close(self) -> None:
        """Releases resources (HTTP clients, ...). Optional."""


class DownloadClient(_Plugin):
    """Receives links and downloads them."""

    @abstractmethod
    def accepts(self, link: str) -> bool:
        """Whether this client can handle the link at all (e.g. only
        ``magnet:`` and ``.torrent`` for a torrent client). The UI only
        offers clients that accept the link."""

    @abstractmethod
    async def add(self, link: str, *, destination: str | None, package_name: str) -> None:
        """Hands the link over. ``destination`` is the download folder the
        files should end up in (``None``: the client's own default).
        ``package_name`` is a readable name for the download (anime title +
        episode) for clients that group downloads. Raise
        DownloadClientError on failure."""


@dataclass(frozen=True)
class SearchQuery:
    """What to look for. ``titles`` holds every known name of the anime,
    the preferred one first -- release names use all of them."""

    titles: list[str]
    anidb_id: int | None = None
    episode: int | None = None  # None: the whole series (wishlist)


@dataclass
class SearchResult:
    title: str
    link: str
    size_bytes: int | None = None
    seeders: int | None = None
    published: str | None = None  # ISO date/time, if the source has one
    info_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class SearchSource(_Plugin):
    """Finds links for an episode or a series."""

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Returns matching links, best first. Raise SearchSourceError on
        failure; return an empty list when there simply are no results."""
