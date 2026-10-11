"""A ready-made two-stage search source for websites, configured purely by
CSS selectors. A plugin subclasses HtmlSiteSource and fills in the class
attributes below -- no parsing code needed. See
core/plugin_examples/vorlage_webseite.py for an annotated template.

How a page is read (all selectors are CSS selectors, as in the browser's
developer tools -- right click an element -> Copy -> Copy selector):

Step 1, the search page (BASE_URL + SEARCH_PATH):
    every element matching SERIES_ITEM is one hit;
    inside it, SERIES_TITLE holds the name and SERIES_LINK the <a> to the
    series page (empty SERIES_LINK: the hit element is the <a> itself).

Step 2, the series page:
    every element matching EPISODE_ITEM is one episode;
    inside it, EPISODE_LABEL holds its name ("Episode 02"), from which
    EPISODE_NUMBER_PATTERN takes the number;
    EPISODE_BODY (optional) narrows down where the variants are;
    a new variant starts at every element matching VARIANT_HEADER (its text,
    e.g. "Subbed", names the variant). Header, details and links may be
    wrapped together or simply follow each other as siblings -- both work.
    Within a variant, DETAIL_ITEM elements become the details shown
    ("Format: MKV"), DOWNLOAD_LINK / STREAM_LINK elements the links.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from app.downloads.base import (
    SearchQuery,
    SearchResult,
    SearchSourceError,
    SeriesHit,
    SettingField,
    TwoStageSearchSource,
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


def _text(element: Tag | None) -> str:
    return " ".join(element.get_text(" ", strip=True).split()) if element is not None else ""


class HtmlSiteSource(TwoStageSearchSource):
    # --- Site --------------------------------------------------------------
    BASE_URL: ClassVar[str] = ""
    # Appended to the base URL; {query} becomes the URL-encoded search term.
    SEARCH_PATH: ClassVar[str] = "/?s={query}"

    # --- Step 1: search results -------------------------------------------------
    SERIES_ITEM: ClassVar[str] = ""
    SERIES_TITLE: ClassVar[str] = ""
    SERIES_LINK: ClassVar[str] = "a"

    # --- Step 2: series page -----------------------------------------------------
    EPISODE_ITEM: ClassVar[str] = ""
    EPISODE_LABEL: ClassVar[str] = ""
    EPISODE_NUMBER_PATTERN: ClassVar[str] = r"(\d+)"
    EPISODE_BODY: ClassVar[str | None] = None
    VARIANT_HEADER: ClassVar[str | None] = None
    DETAIL_ITEM: ClassVar[str | None] = None
    # Optional: label/value inside one DETAIL_ITEM. Without them the item's
    # text is split at DETAIL_SEPARATOR ("Format: MKV"), or shown as a whole.
    DETAIL_LABEL: ClassVar[str | None] = None
    DETAIL_VALUE: ClassVar[str | None] = None
    DETAIL_SEPARATOR: ClassVar[str] = ":"
    DOWNLOAD_LINK: ClassVar[str | None] = None
    STREAM_LINK: ClassVar[str | None] = None

    # --- Links ---------------------------------------------------------------------
    # Regex: links matching it lead to an intermediate page (URL shortener,
    # captcha, ad gate). They're opened in the browser for the user to go
    # through by hand instead of being sent to a download client. ".*" if
    # every link of the site works that way.
    BROWSER_LINK_PATTERN: ClassVar[str | None] = None

    # How many of the anime's titles to try, in order, until the search
    # finds something (sites often know a series under only one name).
    MAX_TITLES_TRIED: ClassVar[int] = 3

    settings_schema = (
        SettingField(
            "base_url",
            "Adresse der Seite",
            help="Nur ändern, wenn die Seite unter eine neue Domain umzieht. Leer: die Adresse aus dem Plugin.",
        ),
    )

    _REQUIRED: ClassVar[tuple[str, ...]] = (
        "BASE_URL", "SERIES_ITEM", "SERIES_TITLE", "EPISODE_ITEM", "EPISODE_LABEL"
    )

    def __init__(self, config: dict[str, Any], http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._http = http_client or httpx.AsyncClient(
            timeout=20.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
        )

    # --- Plumbing --------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return str(self.config.get("base_url") or self.BASE_URL).rstrip("/")

    def _check_configured(self) -> None:
        missing = [name for name in self._REQUIRED if not getattr(self, name)]
        if missing:
            raise SearchSourceError(f"Im Plugin fehlen noch: {', '.join(missing)}")

    async def _fetch(self, url: str) -> BeautifulSoup:
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise SearchSourceError(f"{urlsplit(url).netloc} nicht erreichbar: {exc}") from exc
        if response.status_code in (403, 503) and "cloudflare" in response.text.lower():
            raise SearchSourceError("Die Seite blockiert automatische Abrufe (Cloudflare-Schutz)")
        if response.status_code != 200:
            raise SearchSourceError(f"{urlsplit(url).netloc} antwortet mit HTTP {response.status_code}")
        return BeautifulSoup(response.text, "html.parser")

    def _needs_browser(self, link: str) -> bool:
        return bool(self.BROWSER_LINK_PATTERN and re.search(self.BROWSER_LINK_PATTERN, link))

    async def test_connection(self) -> None:
        self._check_configured()
        await self._fetch(self.base_url + "/")

    async def close(self) -> None:
        await self._http.aclose()

    # --- Step 1 --------------------------------------------------------------------------

    def parse_series(self, soup: BeautifulSoup, page_url: str) -> list[SeriesHit]:
        hits: dict[str, SeriesHit] = {}
        for item in soup.select(self.SERIES_ITEM):
            link = item if not self.SERIES_LINK else item.select_one(self.SERIES_LINK)
            href = link.get("href") if link is not None else None
            if not isinstance(href, str) or not href.strip():
                continue
            url = urljoin(page_url, href.strip())
            title = _text(item.select_one(self.SERIES_TITLE)) or _text(link) or url
            hits.setdefault(url, SeriesHit(title=title, url=url))
        return list(hits.values())

    async def search_series(self, query: SearchQuery) -> list[SeriesHit]:
        self._check_configured()
        for title in query.titles[: self.MAX_TITLES_TRIED]:
            url = self.base_url + self.SEARCH_PATH.format(query=quote_plus(title))
            hits = self.parse_series(await self._fetch(url), url)
            if hits:
                return hits
        return []

    # --- Step 2 --------------------------------------------------------------------------

    def _episode_number(self, label: str) -> int | None:
        match = re.search(self.EPISODE_NUMBER_PATTERN, label)
        if match is None:
            return None
        try:
            return int(match.group(1) if match.groups() else match.group(0))
        except ValueError:
            return None

    def _variants(self, body: Tag) -> list[tuple[str, list[Tag]]]:
        """Splits an episode into (variant name, elements) groups."""
        if not self.VARIANT_HEADER:
            return [("", [body])]
        groups: list[tuple[str, list[Tag]]] = []
        for child in body.find_all(recursive=False):
            header = child if child.css.match(self.VARIANT_HEADER) else child.select_one(self.VARIANT_HEADER)
            if header is not None:
                groups.append((_text(header), [child]))
            elif groups:
                groups[-1][1].append(child)
            else:  # content before the first header
                groups.append(("", [child]))
        return groups

    def _select_all(self, elements: list[Tag], selector: str | None) -> list[Tag]:
        if not selector:
            return []
        found: list[Tag] = []
        for element in elements:
            if element.css.match(selector):
                found.append(element)
            found.extend(element.select(selector))
        return found

    def _details(self, elements: list[Tag]) -> dict[str, str]:
        details: dict[str, str] = {}
        for item in self._select_all(elements, self.DETAIL_ITEM):
            if self.DETAIL_LABEL and self.DETAIL_VALUE:
                label, value = _text(item.select_one(self.DETAIL_LABEL)), _text(item.select_one(self.DETAIL_VALUE))
            else:
                label, _, value = _text(item).partition(self.DETAIL_SEPARATOR)
                if not value:  # no separator: show the text as it is
                    label, value = "", label
            if value:
                details[label.strip() or f"Info {len(details) + 1}"] = value.strip()
        return details

    def parse_releases(self, soup: BeautifulSoup, page_url: str, episode: int | None) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in soup.select(self.EPISODE_ITEM):
            label = _text(item.select_one(self.EPISODE_LABEL))
            number = self._episode_number(label)
            if episode is not None and number != episode:
                continue
            body = item.select_one(self.EPISODE_BODY) if self.EPISODE_BODY else item
            if body is None:
                continue
            for variant, elements in self._variants(body):
                details = self._details(elements)
                for kind, selector in (("download", self.DOWNLOAD_LINK), ("stream", self.STREAM_LINK)):
                    for anchor in self._select_all(elements, selector):
                        href = anchor.get("href")
                        if not isinstance(href, str) or not href.strip():
                            continue
                        link = urljoin(page_url, href.strip())
                        results.append(
                            SearchResult(
                                title=" · ".join(part for part in (label, variant) if part) or page_url,
                                link=link,
                                info_url=page_url,
                                hoster=_text(anchor) or urlsplit(link).netloc,
                                kind=kind,  # type: ignore[arg-type]
                                details=dict(details),
                                needs_browser=self._needs_browser(link),
                                extra={"episode": number} if number is not None else {},
                            )
                        )
        return results

    async def list_releases(self, series: SeriesHit, query: SearchQuery) -> list[SearchResult]:
        self._check_configured()
        return self.parse_releases(await self._fetch(series.url), series.url, query.episode)
