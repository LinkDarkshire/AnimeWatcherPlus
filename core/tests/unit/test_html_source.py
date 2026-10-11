from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest
import respx

from app.downloads import SearchQuery, SearchSourceError, SeriesHit

TEMPLATE = Path(__file__).resolve().parents[2] / "plugin_examples" / "vorlage_webseite.py"
BASE = "https://www.beispiel-seite.example"

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
    spec = importlib.util.spec_from_file_location("vorlage_webseite_test", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MeineSeite


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
