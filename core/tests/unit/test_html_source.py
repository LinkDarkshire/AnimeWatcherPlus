from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest
import respx

from app.downloads import SearchQuery, SearchSourceError, SeriesHit

TEMPLATE = Path(__file__).resolve().parents[2] / "plugin_examples" / "website_template.py"
BASE = "https://www.example-site.example"

SEARCH_PAGE = """
<html><body><div class="results">
  <article class="result-card"><a href="frieren/"><h3>Frieren</h3></a></article>
  <article class="result-card"><a href="/frieren-specials/"><h3>Frieren Specials</h3></a></article>
  <article class="result-card"><h3>Kein Link</h3></article>
</div></body></html>
"""

SERIES_PAGE = """
<html><body><div class="episode-list">
  <div class="episode">
    <div class="episode-header">Episode 01</div>
    <div class="episode-body">
      <div class="variant-header">Subbed</div>
      <div class="variant-actions"><a class="download" href="https://mega.nz/ep1">MEGA</a></div>
    </div>
  </div>
  <div class="episode">
    <div class="episode-header">Episode 02</div>
    <div class="episode-body">
      <div class="variant-header">Subbed</div>
      <div class="variant-meta">
        <span class="meta-item">Format: MKV</span>
        <span class="meta-item">Size: 350 MB</span>
      </div>
      <div class="variant-actions">
        <a class="download" href="https://mega.nz/ep2-sub">MEGA</a>
        <a class="download" href="https://short.example/x1">Pixeldrain</a>
        <a class="stream" href="/watch/2">Stream</a>
      </div>
      <div class="variant-header">RAW</div>
      <div class="variant-meta"><span class="meta-item">Format: MP4</span></div>
      <div class="variant-actions"><a class="download" href="https://mega.nz/ep2-raw">MEGA</a></div>
    </div>
  </div>
</div></body></html>
"""


def _template_class():
    spec = importlib.util.spec_from_file_location("website_template_test", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ExampleSite


@pytest.mark.asyncio
@respx.mock
async def test_series_search_resolves_relative_links_and_skips_linkless_cards() -> None:
    respx.get(f"{BASE}/?s=Frieren").mock(return_value=httpx.Response(200, text=SEARCH_PAGE))

    hits = await _template_class()({}).search_series(SearchQuery(titles=["Frieren"]))

    assert [(h.title, h.url) for h in hits] == [
        ("Frieren", f"{BASE}/frieren/"),
        ("Frieren Specials", f"{BASE}/frieren-specials/"),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_search_falls_back_to_the_next_title() -> None:
    respx.get(f"{BASE}/?s=Sousou+no+Frieren").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(f"{BASE}/?s=Frieren").mock(return_value=httpx.Response(200, text=SEARCH_PAGE))

    hits = await _template_class()({}).search_series(SearchQuery(titles=["Sousou no Frieren", "Frieren"]))

    assert len(hits) == 2


@pytest.mark.asyncio
@respx.mock
async def test_releases_group_sibling_variants_and_filter_the_episode() -> None:
    respx.get(f"{BASE}/frieren/").mock(return_value=httpx.Response(200, text=SERIES_PAGE))
    source_class = _template_class()
    source_class.BROWSER_LINK_PATTERN = r"short\.example"
    try:
        releases = await source_class({}).list_releases(
            SeriesHit(title="Frieren", url=f"{BASE}/frieren/"), SearchQuery(titles=["Frieren"], episode=2)
        )
    finally:
        source_class.BROWSER_LINK_PATTERN = None

    summary = [(r.title, r.hoster, r.kind, r.link, r.needs_browser) for r in releases]
    assert summary == [
        ("Episode 02 · Subbed", "MEGA", "download", "https://mega.nz/ep2-sub", False),
        ("Episode 02 · Subbed", "Pixeldrain", "download", "https://short.example/x1", True),
        ("Episode 02 · Subbed", "Stream", "stream", f"{BASE}/watch/2", False),
        ("Episode 02 · RAW", "MEGA", "download", "https://mega.nz/ep2-raw", False),
    ]
    assert releases[0].details == {"Format": "MKV", "Size": "350 MB"}
    assert releases[3].details == {"Format": "MP4"}


@pytest.mark.asyncio
@respx.mock
async def test_whole_series_lists_every_episode_and_base_url_override() -> None:
    respx.get("https://neue-domain.example/frieren/").mock(return_value=httpx.Response(200, text=SERIES_PAGE))
    source = _template_class()({"base_url": "https://neue-domain.example/"})
    assert source.base_url == "https://neue-domain.example"

    releases = await source.list_releases(
        SeriesHit(title="Frieren", url="https://neue-domain.example/frieren/"), SearchQuery(titles=["Frieren"])
    )
    assert {r.extra["episode"] for r in releases} == {1, 2}


@pytest.mark.asyncio
@respx.mock
async def test_unconfigured_and_blocked_sites_report_clearly() -> None:
    from app.downloads import HtmlSiteSource

    class Empty(HtmlSiteSource):
        id = "empty"
        name = "Empty"

    with pytest.raises(SearchSourceError, match="fehlen noch"):
        await Empty({}).search_series(SearchQuery(titles=["x"]))

    respx.get(f"{BASE}/?s=x").mock(return_value=httpx.Response(403, text="Attention Required | Cloudflare"))
    with pytest.raises(SearchSourceError, match="Cloudflare"):
        await _template_class()({}).search_series(SearchQuery(titles=["x"]))


MIXED_PAGE = """
<div class="episode"><div class="h">Episode 01</div><div class="body">
  <div class="v-header">
    <span class="v-type"><span class="v-icon">📼</span><span class="v-label">Raw</span></span>
    <span class="v-badge">Censored</span>
  </div>
  <div class="v-meta">
    <div class="m-item"><div class="m-label">Format</div><div class="m-value">MP4</div></div>
    <div class="m-item"><div class="m-label">Size</div><div class="m-value"> 103 MB </div></div>
    <div class="m-item"><div class="m-label">Subs</div><div class="m-value"><span>⌀</span><span>None</span></div></div>
    <div class="m-item"><div class="m-label">Audio</div><div class="m-value"><span>🇯🇵</span><span>Japanese</span></div></div>
  </div>
  <div class="v-actions">
    <div class="a-item"><div class="a-label">Download</div>
      <div class="a-wrap"><a class="a-value" href="/out/?sv=a&amp;id=1">HostA</a><a class="a-value" href="/out/?sv=b&amp;id=1">Torrent</a></div>
    </div>
    <div class="a-item"><div class="a-label">Stream</div>
      <div class="a-wrap"><a class="a-value" href="/watch/1">Player</a></div>
    </div>
  </div>
</div></div>
"""


def test_mixed_values_variant_name_and_label_based_link_sections() -> None:
    from bs4 import BeautifulSoup

    from app.downloads import HtmlSiteSource

    class Mixed(HtmlSiteSource):
        id = "mixed"
        name = "Mixed"
        EPISODE_ITEM = "div.episode"
        EPISODE_LABEL = "div.h"
        EPISODE_BODY = "div.body"
        VARIANT_HEADER = "div.v-header"
        VARIANT_NAME = "span.v-label, span.v-badge"
        DETAIL_ITEM = "div.m-item"
        DETAIL_LABEL = "div.m-label"
        DETAIL_VALUE = ("div.m-value span:last-child", "div.m-value")
        DOWNLOAD_LINK = 'div.a-item:has(> div.a-label:-soup-contains("Download")) a.a-value'
        STREAM_LINK = 'div.a-item:has(> div.a-label:-soup-contains("Stream")) a.a-value'
        BROWSER_LINK_PATTERN = r"/out/"

    releases = Mixed({}).parse_releases(BeautifulSoup(MIXED_PAGE, "html.parser"), "https://site.example/show/", 1)

    assert [(r.title, r.hoster, r.kind, r.needs_browser) for r in releases] == [
        ("Episode 01 · Raw · Censored", "HostA", "download", True),
        ("Episode 01 · Raw · Censored", "Torrent", "download", True),
        ("Episode 01 · Raw · Censored", "Player", "stream", False),
    ]
    assert releases[0].link == "https://site.example/out/?sv=a&id=1"
    assert releases[0].details == {"Format": "MP4", "Size": "103 MB", "Subs": "None", "Audio": "Japanese"}


def test_fallback_search_terms_strip_words_then_first_word() -> None:
    from app.downloads import fallback_search_terms

    assert fallback_search_terms(["OVA Tensura Nikki", "Tensura Nikki: The Animation"]) == [
        "OVA Tensura Nikki",
        "Tensura Nikki: The Animation",
        "Tensura Nikki",
        "Tensura",
    ]
    assert fallback_search_terms(["Frieren"]) == ["Frieren"]
    assert fallback_search_terms(["A", "B", "C", "D"], max_titles=2) == ["A", "B"]


@pytest.mark.asyncio
@respx.mock
async def test_search_strips_ova_and_reports_tried_terms() -> None:
    from app.downloads import NothingFound

    respx.get(f"{BASE}/?s=OVA+Frieren+Special").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(f"{BASE}/?s=Frieren+Special").mock(return_value=httpx.Response(200, text=SEARCH_PAGE))
    hits = await _template_class()({}).search_series(SearchQuery(titles=["OVA Frieren Special"]))
    assert len(hits) == 2

    respx.get(url__startswith=f"{BASE}/?s=").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(NothingFound) as caught:
        await _template_class()({}).search_series(SearchQuery(titles=["OVA Nichts Da"]))
    assert "„OVA Nichts Da“, „Nichts Da“, „Nichts“" in str(caught.value)
