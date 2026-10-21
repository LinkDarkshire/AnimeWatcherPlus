"""A post shared to the app (e.g. from X on the phone) turned into wishlist
suggestions: the post's text is searched for anime titles in the local
AniDB title list.

X's share sheet usually hands over just the link, so the text of an X post
is fetched through X's public oEmbed endpoint (the one websites use to
embed posts; no account or key involved).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import wishlist

logger = structlog.get_logger(__name__)

OEMBED_URL = "https://publish.twitter.com/oembed"
_URL_RE = re.compile(r"https?://\S+")
_X_POST_RE = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w+/status/\d+", re.IGNORECASE)
_ANIDB_RE = re.compile(r"^https?://(?:www\.)?anidb\.net/(?:anime/|perl-bin/animedb\.pl\?show=anime&aid=)(\d+)")
# Titles are often quoted: 「…」 『…』 “…” "…" „…“
_QUOTED_RE = re.compile(r"「([^」]{2,80})」|『([^』]{2,80})』|“([^”]{2,80})”|\"([^\"]{2,80})\"|„([^“]{2,80})“")
_HASHTAG_RE = re.compile(r"#(\w{3,60})")
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")

MIN_SCORE = 90.0
# Per query only the best match and those close to it: fuzzy scoring rates
# a title sharing one word with a line of text surprisingly high.
CLOSE_TO_BEST = 3.0
MAX_SUGGESTIONS = 8
MAX_QUERIES = 12


@dataclass
class SharedPost:
    text: str
    source_url: str | None = None
    suggestions: list[wishlist.WishlistCandidate] = field(default_factory=list)


async def _fetch_x_post(url: str, client: httpx.AsyncClient) -> str | None:
    try:
        response = await client.get(OEMBED_URL, params={"url": url, "omit_script": "1", "dnt": "true"}, timeout=8.0)
        response.raise_for_status()
        html = response.json().get("html", "")
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("x_post_unavailable", url=url, error=str(exc))
        return None
    paragraph = BeautifulSoup(html, "html.parser").find("p")
    return paragraph.get_text(" ", strip=True) if paragraph else None


def candidate_queries(text: str) -> list[str]:
    """Where a title might be in a post, most specific first: quoted
    phrases, hashtags, then each line on its own."""
    queries: list[str] = []
    for match in _QUOTED_RE.finditer(text):
        queries.append(next(group for group in match.groups() if group))
    for tag in _HASHTAG_RE.findall(text):
        queries.append(_CAMEL_RE.sub(" ", tag).replace("_", " "))
    without_noise = _HASHTAG_RE.sub(" ", _URL_RE.sub(" ", text))
    for line in without_noise.splitlines():
        line = line.strip(" \t-\u2013\u2014:|\u00b7\u2022")  # dashes, dots, bullets
        if 2 <= len(line) <= 100:
            queries.append(line)
    unique = list(dict.fromkeys(q.strip() for q in queries if q.strip()))
    return unique[:MAX_QUERIES]


async def resolve(session: AsyncSession, shared: str, client: httpx.AsyncClient | None = None) -> SharedPost:
    shared = shared.strip()
    urls = _URL_RE.findall(shared)
    text = _URL_RE.sub(" ", shared).strip()
    post = SharedPost(text=text)

    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        for url in urls:
            if match := _X_POST_RE.match(url):
                # Without the share tracking (?s=20&t=...).
                post.source_url = match.group(0)
                fetched = await _fetch_x_post(post.source_url, client)
                if fetched:
                    post.text = f"{text}\n{fetched}".strip()
                break
    finally:
        if owns_client:
            await client.aclose()

    found: dict[int, wishlist.WishlistCandidate] = {}
    # A link straight to AniDB names the anime outright.
    for url in urls:
        if match := _ANIDB_RE.match(url):
            for candidate in await wishlist.search(session, match.group(1)):
                found[candidate.anidb_id] = candidate
    for query in candidate_queries(post.text):
        results = await wishlist.search(session, query, limit=5)
        if not results:
            continue
        cutoff = max(MIN_SCORE, max(c.score for c in results) - CLOSE_TO_BEST)
        for candidate in results:
            if candidate.score < cutoff:
                continue
            known = found.get(candidate.anidb_id)
            if known is None or candidate.score > known.score:
                found[candidate.anidb_id] = candidate
    post.suggestions = sorted(found.values(), key=lambda c: c.score, reverse=True)[:MAX_SUGGESTIONS]
    return post
