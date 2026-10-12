"""Template: a search source for a website -- fill in the address and CSS selectors.

How to use it:
  1. Copy this file into the app's plugins folder and rename it
     (e.g. my_site.py). The download page shows the folder under "Einrichtung".
  2. Fill in `id`, `name`, BASE_URL and the CSS selectors for your site below.
  3. Restart the app, add the source on the download page under
     "Einrichtung" and click "Testen".

Finding selectors: in the browser, right-click the element -> "Inspect", then
right-click the highlighted line in the developer tools -> "Copy" ->
"Copy selector". A class name is usually shorter and sturdier than the copied
path: <article class="result-card dim"> becomes "article.result-card".
A space means "anywhere below", ">" means "directly below".

All selectors except SERIES_ITEM and EPISODE_ITEM are RELATIVE to the element
above them -- the page is read from the outside in.

The values below belong to a made-up site built like this:

  Search page  https://www.example-site.example/?s=frieren
    <div class="results">
      <article class="result-card">
        <a href="frieren/"><h3>Frieren</h3></a>
      </article>
      ...
    </div>

  Series page  https://www.example-site.example/frieren/
    <div class="episode-list">
      <div class="episode">
        <div class="episode-header">Episode 02</div>
        <div class="episode-body">
          <div class="variant-header">Subbed</div>          <- variant 1
          <div class="variant-meta">
            <span class="meta-item">Format: MKV</span>
            <span class="meta-item">Size: 350 MB</span>
          </div>
          <div class="variant-actions">
            <a class="download" href="https://mega.nz/...">MEGA</a>
            <a class="stream" href="/watch/2">Stream</a>
          </div>
          <div class="variant-header">RAW</div>             <- variant 2
          ...
        </div>
      </div>
    </div>
"""

from __future__ import annotations

from app.downloads import HtmlSiteSource


class ExampleSite(HtmlSiteSource):
    # Unique id (lowercase letters and underscores). Don't change it once the
    # source is set up -- saved setups refer to it.
    id = "website_template"
    name = "Website template"
    description = "Example source -- adjust the address and selectors before use."

    # --- Site ----------------------------------------------------------------
    BASE_URL = "https://www.example-site.example"
    # Appended to BASE_URL; {query} is the search term (URL-encoded for you).
    # Examples: "/?s={query}", "/search?q={query}", "/search/{query}/".
    SEARCH_PATH = "/?s={query}"

    # --- Step 1: search results ---------------------------------------------------
    # One element per hit (searched across the whole page).
    SERIES_ITEM = "div.results article.result-card"
    # Inside it: the hit's name.
    SERIES_TITLE = "a h3"
    # Inside it: the link to the series page (the <a> element). Relative links
    # like "frieren/" are completed to a full address automatically.
    # Leave empty ("") if SERIES_ITEM itself is the <a>.
    SERIES_LINK = "a"

    # --- Step 2: series page -------------------------------------------------------
    # One element per episode (searched across the whole page).
    EPISODE_ITEM = "div.episode-list div.episode"
    # Inside it: the episode's name, e.g. "Episode 02".
    EPISODE_LABEL = "div.episode-header"
    # How the episode number is read from that name: the first number.
    # Other patterns: r"Episode\s*(\d+)", r"E(\d+)".
    EPISODE_NUMBER_PATTERN = r"(\d+)"
    # Optional: the part of the episode that holds the variants.
    # None = the whole episode element.
    EPISODE_BODY = "div.episode-body"
    # Optional: each match starts a new variant (language, sub/raw, ...); its
    # text becomes the variant's name. A variant's header, details and links
    # may share one wrapping element OR simply follow each other (as in the
    # example above) -- both work. None = one variant per episode.
    VARIANT_HEADER = "div.variant-header"
    # Optional: the parts of the header that make up the name (relative to
    # VARIANT_HEADER). All matches count, joined with " · ":
    # "span.label, span.badge" gives e.g. "Raw · Censored" and keeps icons
    # out of the name. None = the header's whole text.
    VARIANT_NAME = None
    # Optional: a variant's details (format, size, subtitles, audio).
    DETAIL_ITEM = "span.meta-item"
    # How one detail splits into label and value ("Format: MKV").
    # If both sit in their own elements, set DETAIL_LABEL and DETAIL_VALUE
    # instead (relative to DETAIL_ITEM). DETAIL_VALUE may also be a tuple,
    # tried in order -- for values that are sometimes in a <span> (often with
    # a flag or icon before it) and sometimes directly in the element:
    #     DETAIL_VALUE = ("div.value span:last-child", "div.value")
    DETAIL_SEPARATOR = ":"
    DETAIL_LABEL = None
    DETAIL_VALUE = None
    # Download links (the <a> element). The link text is shown as the hoster
    # ("MEGA"); several links per variant are normal.
    # If the download and stream areas only differ by their label,
    # :-soup-contains("Text") helps (works in the app, not in the browser
    # console):
    #     'div.action:has(> div.label:-soup-contains("Download")) a'
    DOWNLOAD_LINK = "div.variant-actions a.download"
    # Optional: stream links. Only shown (opened in the browser), never sent
    # to a download client. None = don't show any.
    STREAM_LINK = "div.variant-actions a.stream"

    # --- Links through an intermediate page ------------------------------------------
    # Regular expression for links that lead through an intermediate page (URL
    # shortener, captcha, ad page). The app opens those in the browser; the
    # link you end up at goes into the link field by hand. Examples:
    # r"ouo\.io|shrinkme" -- or r".*" if every link of the site works that
    # way. None = use all links directly.
    BROWSER_LINK_PATTERN = None

    # The search runs in three rounds until something turns up:
    #   1. the anime's titles (English, romanized, ...) -- as many as
    #      MAX_TITLES_TRIED,
    #   2. the same titles without the words in STRIP_WORDS
    #      ("OVA Tensura Nikki" -> "Tensura Nikki"),
    #   3. just the first word ("Tensura").
    # If no round finds anything, the app shows what was searched for.
    MAX_TITLES_TRIED = 3
    STRIP_WORDS = ("OVA", "ONA", "The Animation")
