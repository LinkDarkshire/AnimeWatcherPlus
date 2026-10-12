"""Download clients and search sources. Plugins import from here."""

from app.downloads.base import (
    DEFAULT_STRIP_WORDS,
    DownloadClient,
    DownloadClientError,
    DownloadStatus,
    NothingFound,
    PluginError,
    SearchQuery,
    SearchResult,
    SearchSource,
    SearchSourceError,
    SeriesHit,
    SettingField,
    TwoStageSearchSource,
    fallback_search_terms,
)
from app.downloads.html_source import HtmlSiteSource

__all__ = [
    "DEFAULT_STRIP_WORDS",
    "DownloadClient",
    "DownloadClientError",
    "DownloadStatus",
    "HtmlSiteSource",
    "NothingFound",
    "PluginError",
    "SearchQuery",
    "SearchResult",
    "SearchSource",
    "SearchSourceError",
    "SeriesHit",
    "SettingField",
    "TwoStageSearchSource",
    "fallback_search_terms",
]
