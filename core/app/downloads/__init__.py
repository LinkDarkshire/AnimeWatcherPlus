"""Download clients and search sources. Plugins import from here."""

from app.downloads.base import (
    DownloadClient,
    DownloadClientError,
    PluginError,
    SearchQuery,
    SearchResult,
    SearchSource,
    SearchSourceError,
    SeriesHit,
    SettingField,
    TwoStageSearchSource,
)
from app.downloads.html_source import HtmlSiteSource

__all__ = [
    "DownloadClient",
    "DownloadClientError",
    "HtmlSiteSource",
    "PluginError",
    "SearchQuery",
    "SearchResult",
    "SearchSource",
    "SearchSourceError",
    "SeriesHit",
    "SettingField",
    "TwoStageSearchSource",
]
