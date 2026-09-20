from __future__ import annotations

import time
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import structlog

from app.config import Settings
from app.domain.metadata import AnimeMetadata, EpisodeInfo, ProviderManifest, SearchHit, TagInfo
from app.domain.titles import (
    DEFAULT_TITLE_ORDER,
    TITLE_VARIANT_EN,
    TITLE_VARIANT_JA,
    TITLE_VARIANT_MAIN,
    Variants,
    pick_variants,
    resolve_title,
)
from app.providers.base import CircuitBreaker, MetadataProvider, ProviderBannedError, RateLimiter

logger = structlog.get_logger(__name__)

ANIDB_HTTP_API = "http://api.anidb.net:9001/httpapi"
ANIDB_PICTURE_BASE = "http://img7.anidb.net/pics/anime/"
CACHE_TTL_S = 7 * 24 * 3600  # NFA-04: 7 Tage Response-Cache
BAN_SETTING_KEY = "anidb_banned_until"  # Setting.value: wall-clock time.time() epoch seconds


def cache_dir(settings: Settings) -> Path:
    return settings.data_dir / "cache" / "anidb"


def cached_metadata(settings: Settings, aid: int) -> AnimeMetadata | None:
    """The full parsed metadata from the on-disk response cache, ignoring its
    freshness window. Lets the repair scan restore titles, year, type,
    description and the episode list for anime the staleness rule keeps out of
    rescans -- without a single request."""
    try:
        xml_bytes = (cache_dir(settings) / f"{aid}.xml").read_bytes()
    except OSError:
        return None
    return _parse_anime_xml(xml_bytes, aid)


def cached_title_variants(settings: Settings, aid: int) -> Variants | None:
    """Just the title variants from the cached response -- the repair scan's
    cheapest useful recovery, and all the startup backfill needs. Returns None
    when nothing usable is cached (missing file, unparseable, or an error
    response, which carries no titles)."""
    metadata = cached_metadata(settings, aid)
    if metadata is None:
        return None
    variants = {
        TITLE_VARIANT_MAIN: metadata.title_main,
        TITLE_VARIANT_EN: metadata.title_en,
        TITLE_VARIANT_JA: metadata.title_ja,
    }
    return variants if any(variants.values()) else None


class AniDBProvider(MetadataProvider):
    """Reference metadata provider (A-06): registered HTTP client, strict rate
    limiting, ban detection, and a 7-day on-disk response cache so repeated scans
    of an unchanged library never re-hit the API (NFA-04, goal: 0 API bans).
    """

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.manifest = ProviderManifest(
            plugin_id="anidb",
            name="AniDB",
            version="1.0",
            min_interval_s=settings.anidb_min_interval_s,
            daily_cap=settings.anidb_daily_cap,
        )
        self._settings = settings
        self._client = http_client or httpx.AsyncClient()
        self._limiter = RateLimiter(settings.anidb_min_interval_s, settings.anidb_daily_cap)
        self.circuit_breaker = CircuitBreaker()
        self._cache_dir = cache_dir(settings)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # Wall-clock (time.time()), not monotonic: this must survive a
        # process restart during the ~24h ban window (Kap. 9.3 Edge Case 6),
        # so a restart can't accidentally resume hammering a still-banned API.
        self._banned_until: float = 0.0

    async def load_ban_state(self) -> None:
        """Restores a still-active ban across a process restart. Call once
        at startup, before the scanner/job-queue starts issuing any fetches.
        """
        from app.db.models import Setting
        from app.db.session import session_scope

        async with session_scope() as session:
            row = await session.get(Setting, BAN_SETTING_KEY)
            value = row.value if row is not None else None

        if isinstance(value, (int, float)):
            self._banned_until = float(value)
            if self._banned_until > time.time():
                logger.warning(
                    "anidb_ban_restored_from_previous_run",
                    banned_until_epoch=self._banned_until,
                    remaining_s=self._banned_until - time.time(),
                )

    async def _persist_ban_state(self) -> None:
        from app.db.models import Setting
        from app.db.session import session_scope

        async with session_scope() as session:
            row = await session.get(Setting, BAN_SETTING_KEY)
            if row is None:
                session.add(Setting(key=BAN_SETTING_KEY, value=self._banned_until))
            else:
                row.value = self._banned_until
            await session.commit()

    async def search(self, title: str, year: int | None) -> list[SearchHit]:
        # AniDB has no public HTTP text-search endpoint; the identification
        # pipeline resolves titles via the local title dump (titledump.fuzzy_match)
        # before ever calling fetch(). See Kap. 4.4 sequence diagram.
        return []

    async def fetch(self, external_id: str) -> AnimeMetadata | None:
        xml_bytes = await self._get_xml(int(external_id))
        if xml_bytes is None:
            return None
        return _parse_anime_xml(xml_bytes, int(external_id))

    async def get_full_info(self, external_id: str) -> dict | None:
        """Everything the HTTP API returns for this anime (ratings, creators,
        related anime, full per-episode detail incl. summaries) -- used to
        write the aniinfo.json sidecar, which is a superset of the Jellyfin-
        shaped tvshow.nfo. Reuses the same on-disk cache as fetch(), so
        calling both for the same anime costs one network request, not two.
        """
        aid = int(external_id)
        xml_bytes = await self._get_xml(aid)
        if xml_bytes is None:
            return None
        return parse_full_anime_info(xml_bytes, aid)

    async def _get_xml(self, aid: int) -> bytes | None:
        cached = self._read_cache(aid)
        if cached is not None:
            return cached

        if time.time() < self._banned_until:
            raise ProviderBannedError("AniDB is in a ban cool-down period")
        if self.circuit_breaker.is_open():
            raise ProviderBannedError("AniDB circuit breaker is open")

        xml_bytes = await self._request_with_retry(aid)
        if xml_bytes is None:
            self.circuit_breaker.record_failure()
            return None

        if _is_error_response(xml_bytes):
            error_text = _extract_error_text(xml_bytes)
            if "ban" in error_text.lower():
                # AniDB doesn't document how long a ban lasts (karma-based,
                # per the wiki) -- this is a configurable heuristic cool-down,
                # not a guaranteed recovery time. Persisted so a restart
                # during the ban doesn't resume hammering the API.
                self._banned_until = time.time() + self._settings.anidb_ban_cooldown_s
                await self._persist_ban_state()
                logger.error("anidb_banned", detail=error_text, cooldown_s=self._settings.anidb_ban_cooldown_s)
                raise ProviderBannedError(error_text)
            logger.warning("anidb_error_response", detail=error_text)
            self.circuit_breaker.record_failure()
            return None

        self.circuit_breaker.record_success()
        self._write_cache(aid, xml_bytes)
        return xml_bytes

    async def _request_with_retry(self, aid: int, max_retries: int = 3) -> bytes | None:
        backoff = 1.0
        for attempt in range(max_retries):
            try:
                await self._limiter.acquire()
                response = await self._client.get(
                    ANIDB_HTTP_API,
                    params={
                        "request": "anime",
                        # AniDB requires the registered client string lower-case
                        # on the wire, regardless of how it's displayed/stored
                        # (https://wiki.anidb.net/HTTP_API_Definition).
                        "client": self._settings.anidb_client_name.lower(),
                        "clientver": self._settings.anidb_client_version,
                        "protover": 1,
                        "aid": aid,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.content
            except ProviderBannedError:
                raise
            except httpx.HTTPError as exc:
                logger.warning("anidb_request_failed", attempt=attempt, error=str(exc))
                if attempt == max_retries - 1:
                    return None
                import asyncio

                await asyncio.sleep(backoff)
                backoff *= 2
        return None

    def _cache_path(self, aid: int) -> Path:
        return self._cache_dir / f"{aid}.xml"

    def _read_cache(self, aid: int) -> bytes | None:
        path = self._cache_path(aid)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > CACHE_TTL_S:
            return None
        return path.read_bytes()

    def _write_cache(self, aid: int, data: bytes) -> None:
        self._cache_path(aid).write_bytes(data)


def _is_error_response(xml_bytes: bytes) -> bool:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return True
    return root.tag == "error"


def _extract_error_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
        return root.text or root.tag
    except ET.ParseError:
        return "unparseable response"


_XML_LANG_ATTR = "{http://www.w3.org/XML/1998/namespace}lang"


def _extract_all_titles(root: ET.Element) -> list[tuple[str, str | None, str | None]]:
    all_titles: list[tuple[str, str | None, str | None]] = []
    titles_el = root.find("titles")
    if titles_el is not None:
        for t in titles_el.findall("title"):
            if t.text:
                all_titles.append((t.text, t.get(_XML_LANG_ATTR), t.get("type")))
    return all_titles


def _pick_primary_and_original(
    all_titles: list[tuple[str, str | None, str | None]], aid: int
) -> tuple[str, str | None, Variants]:
    """Returns (primary title, original/main title, the three language
    variants).

    AniDB lists titles in an arbitrary language order per anime, and within
    one language emits several entries of differing quality, so the split into
    variants (domain.titles.pick_variants) ranks by title *type* per language
    rather than taking whichever entry happens to come first in document
    order. The primary title here is only a default: it follows
    DEFAULT_TITLE_ORDER, and the identification pipeline re-resolves it
    against the user's configured `display_title_order` before persisting.
    """
    variants = pick_variants(all_titles)
    fallback = all_titles[0][0] if all_titles else f"AniDB #{aid}"
    title = resolve_title(variants, DEFAULT_TITLE_ORDER, fallback)
    return title, variants[TITLE_VARIANT_MAIN], variants


def _parse_tags(root: ET.Element) -> list[TagInfo]:
    tags: list[TagInfo] = []
    tags_el = root.find("tags")
    if tags_el is not None:
        for tag_el in tags_el.findall("tag"):
            name_el = tag_el.find("name")
            if name_el is None or not name_el.text:
                continue
            tag_id = tag_el.get("id")
            weight = tag_el.get("weight")
            tags.append(
                TagInfo(
                    name=name_el.text,
                    weight=int(weight) if weight and weight.isdigit() else 0,
                    anidb_tag_id=int(tag_id) if tag_id and tag_id.isdigit() else None,
                )
            )
    return tags


_EPISODE_TITLE_LANG_PREFERENCE = ("en", "x-jat", "ja")


def _pick_preferred_episode_title(ep_el: ET.Element) -> str | None:
    """Same language cascade as `_pick_primary_and_original` (English, then
    romanized Japanese, then Japanese script), applied per-episode -- AniDB
    emits one `<title xml:lang="...">` per language for each episode, and
    `ep_el.find("title")` alone (the old behavior) just grabbed whichever one
    happened to come first in document order."""
    by_lang: dict[str | None, str] = {}
    first: str | None = None
    for t in ep_el.findall("title"):
        if not t.text:
            continue
        if first is None:
            first = t.text
        lang = t.get(_XML_LANG_ATTR)
        if lang not in by_lang:
            by_lang[lang] = t.text
    for lang in _EPISODE_TITLE_LANG_PREFERENCE:
        if lang in by_lang:
            return by_lang[lang]
    return first


def _parse_anime_xml(xml_bytes: bytes, aid: int) -> AnimeMetadata | None:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    all_titles = _extract_all_titles(root)
    title, main_title, variants = _pick_primary_and_original(all_titles, aid)
    alt_titles = [text for text, _, _ in all_titles if text != title]

    year = None
    startdate = root.findtext("startdate")
    if startdate and len(startdate) >= 4 and startdate[:4].isdigit():
        year = int(startdate[:4])

    media_type = root.findtext("type")
    description = root.findtext("description")

    picture = root.findtext("picture")
    poster_url = f"{ANIDB_PICTURE_BASE}{picture}" if picture else None

    tags = _parse_tags(root)

    episodes: list[EpisodeInfo] = []
    episodes_el = root.find("episodes")
    if episodes_el is not None:
        for ep_el in episodes_el.findall("episode"):
            epno_el = ep_el.find("epno")
            if epno_el is None or not epno_el.text:
                continue
            episodes.append(
                EpisodeInfo(
                    ep_number=epno_el.text,
                    title=_pick_preferred_episode_title(ep_el),
                    air_date=ep_el.findtext("airdate"),
                )
            )

    return AnimeMetadata(
        external_id=str(aid),
        title=title,
        original_title=main_title,
        title_main=variants[TITLE_VARIANT_MAIN],
        title_en=variants[TITLE_VARIANT_EN],
        title_ja=variants[TITLE_VARIANT_JA],
        alt_titles=alt_titles,
        year=year,
        media_type=media_type,
        description=description,
        poster_url=poster_url,
        tags=tags,
        episodes=episodes,
    )


def _parse_rating(el: ET.Element | None) -> dict | None:
    if el is None or not el.text:
        return None
    votes = el.get("count") or el.get("votes")
    try:
        value = float(el.text)
    except ValueError:
        return None
    return {"value": value, "votes": int(votes) if votes and votes.isdigit() else None}


def parse_full_anime_info(xml_bytes: bytes, aid: int) -> dict | None:
    """Everything the AniDB HTTP API returns for one anime, as a plain dict
    ready for `json.dump` -- the source for the aniinfo.json sidecar file,
    which is deliberately a superset of what the Jellyfin-shaped tvshow.nfo
    can express (full title list per language, ratings, creators, related
    anime, and per-episode length/rating/summary/multi-language titles).
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    all_titles = _extract_all_titles(root)
    primary_title, original_title, _ = _pick_primary_and_original(all_titles, aid)

    picture = root.findtext("picture")

    related_anime = []
    related_el = root.find("relatedanime")
    if related_el is not None:
        for anime_el in related_el.findall("anime"):
            related_id = anime_el.get("id")
            related_anime.append(
                {
                    "anidb_id": int(related_id) if related_id and related_id.isdigit() else None,
                    "relation_type": anime_el.get("type"),
                    "title": anime_el.text,
                }
            )

    creators = []
    creators_el = root.find("creators")
    if creators_el is not None:
        for name_el in creators_el.findall("name"):
            creator_id = name_el.get("id")
            creators.append(
                {
                    "anidb_creator_id": int(creator_id) if creator_id and creator_id.isdigit() else None,
                    "name": name_el.text,
                    "role": name_el.get("type"),
                }
            )

    ratings_el = root.find("ratings")
    ratings = None
    if ratings_el is not None:
        ratings = {
            "permanent": _parse_rating(ratings_el.find("permanent")),
            "temporary": _parse_rating(ratings_el.find("temporary")),
            "review": _parse_rating(ratings_el.find("review")),
        }

    episodes = []
    episodes_el = root.find("episodes")
    if episodes_el is not None:
        for ep_el in episodes_el.findall("episode"):
            epno_el = ep_el.find("epno")
            if epno_el is None or not epno_el.text:
                continue
            ep_titles = {
                t.get(_XML_LANG_ATTR): t.text for t in ep_el.findall("title") if t.text and t.get(_XML_LANG_ATTR)
            }
            length = ep_el.findtext("length")
            episodes.append(
                {
                    "episode_id": ep_el.get("id"),
                    "ep_number": epno_el.text,
                    "ep_type": epno_el.get("type"),
                    "length_minutes": int(length) if length and length.isdigit() else None,
                    "air_date": ep_el.findtext("airdate"),
                    "rating": _parse_rating(ep_el.find("rating")),
                    "titles": ep_titles,
                    "summary": ep_el.findtext("summary"),
                }
            )

    restricted = root.get("restricted")

    return {
        "anidb_id": aid,
        "restricted": restricted == "true",
        "type": root.findtext("type"),
        "start_date": root.findtext("startdate"),
        "end_date": root.findtext("enddate"),
        "episode_count_official": _int_or_none(root.findtext("episodecount")),
        "primary_title": primary_title,
        "original_title": original_title,
        "titles": [
            {"language": lang, "type": ttype, "value": text} for text, lang, ttype in all_titles
        ],
        "description": root.findtext("description"),
        "picture": picture,
        "poster_url": f"{ANIDB_PICTURE_BASE}{picture}" if picture else None,
        "ratings": ratings,
        "tags": [
            {"anidb_tag_id": t.anidb_tag_id, "name": t.name, "weight": t.weight} for t in _parse_tags(root)
        ],
        "creators": creators,
        "related_anime": related_anime,
        "episodes": episodes,
    }


def _int_or_none(value: str | None) -> int | None:
    if value and value.isdigit():
        return int(value)
    return None
