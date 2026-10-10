from __future__ import annotations

import gzip
import re
import time
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx
import structlog
from rapidfuzz import fuzz, process, utils as fuzz_utils
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AnidbTitleEntry, Setting
from app.db.session import session_scope
from app.services.settings_store import get_setting

logger = structlog.get_logger(__name__)

TITLE_DUMP_URL = "https://anidb.net/api/anime-titles.xml.gz"
TITLE_DUMP_IMPORTED_AT_KEY = "titledump_imported_at"  # Setting.value: time.time() epoch seconds
TITLE_DUMP_MAX_AGE_S = 7 * 24 * 3600

_BRACKET_RE = re.compile(r"[\[(（【][^\])）】]*[\])）】]")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_SEP_RE = re.compile(r"[._]+")
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SCENE_WORDS_RE = re.compile(
    r"\b(BD|BDRip|BluRay|Complete|Batch|WEB|WEBRip|HEVC|x264|x265|1080p|720p|480p|HD|SD)\b",
    re.IGNORECASE,
)


def normalize_folder_name(name: str) -> str:
    """FA-05: normalize a release/folder name before fuzzy-matching it against the
    local AniDB title dump (strip bracketed tags, dots/underscores, extra whitespace).
    """
    normalized = _BRACKET_RE.sub(" ", name)
    normalized = _YEAR_RE.sub(" ", normalized)
    normalized = _SCENE_WORDS_RE.sub(" ", normalized)
    normalized = _SEP_RE.sub(" ", normalized)
    normalized = _WS_RE.sub(" ", normalized).strip().lower()
    return normalized


@dataclass(frozen=True)
class TitleRow:
    aid: int
    title: str
    lang: str | None
    title_type: str | None


def parse_title_dump(xml_bytes_gz: bytes) -> list[TitleRow]:
    xml_bytes = gzip.decompress(xml_bytes_gz)
    root = ET.fromstring(xml_bytes)
    rows: list[TitleRow] = []
    for anime_el in root.findall("anime"):
        aid_str = anime_el.get("aid")
        if not aid_str:
            continue
        aid = int(aid_str)
        for title_el in anime_el.findall("title"):
            if not title_el.text:
                continue
            lang = title_el.get("{http://www.w3.org/XML/1998/namespace}lang")
            title_type = title_el.get("type")
            rows.append(TitleRow(aid=aid, title=title_el.text.strip(), lang=lang, title_type=title_type))
    return rows


async def download_title_dump(client: httpx.AsyncClient) -> bytes:
    response = await client.get(TITLE_DUMP_URL, timeout=60.0)
    response.raise_for_status()
    return response.content


async def import_title_dump(session: AsyncSession, xml_bytes_gz: bytes) -> int:
    """Wholesale-replaces the local title index (Kap. 6.1: "wird komplett ersetzt
    statt migriert"). FTS5 mirror table is kept in sync by DB triggers.
    """
    rows = parse_title_dump(xml_bytes_gz)
    await session.execute(delete(AnidbTitleEntry))
    if rows:
        # Bulk executemany via Core insert(); row-by-row ORM add_all() took ~65s
        # for ~100k rows in testing, this is roughly an order of magnitude faster.
        await session.execute(
            insert(AnidbTitleEntry),
            [{"aid": r.aid, "title": r.title, "lang": r.lang, "title_type": r.title_type} for r in rows],
        )
    await session.commit()
    logger.info("titledump_imported", rows=len(rows))
    return len(rows)


async def ensure_title_dump_imported(settings: Settings) -> None:
    """Runs once at startup (as a background job): downloads and imports the
    title dump when the local index is empty or older than
    TITLE_DUMP_MAX_AGE_S. Without the age check a library would never learn
    any anime announced after its first start, and every new series would
    land in needs_manual_id. Well within AniDB's limit of one dump download
    per day. A failed download keeps the existing index.
    """
    async with session_scope() as session:
        count = (await session.execute(select(func.count()).select_from(AnidbTitleEntry))).scalar_one()
        imported_at = await get_setting(session, TITLE_DUMP_IMPORTED_AT_KEY, None)
    fresh = isinstance(imported_at, (int, float)) and time.time() - imported_at < TITLE_DUMP_MAX_AGE_S
    if count > 0 and fresh:
        return
    async with httpx.AsyncClient() as client:
        try:
            xml_bytes_gz = await download_title_dump(client)
        except httpx.HTTPError:
            logger.exception("titledump_download_failed")
            return
    async with session_scope() as session:
        await import_title_dump(session, xml_bytes_gz)
        row = await session.get(Setting, TITLE_DUMP_IMPORTED_AT_KEY)
        if row is None:
            session.add(Setting(key=TITLE_DUMP_IMPORTED_AT_KEY, value=time.time()))
        else:
            row.value = time.time()
        await session.commit()


@dataclass(frozen=True)
class FuzzyCandidate:
    aid: int
    title: str
    score: float


async def fuzzy_match(session: AsyncSession, folder_name: str, limit: int = 5) -> list[FuzzyCandidate]:
    """FA-05: resolve a normalized folder name against the local title dump only
    (no per-search API calls, per NFA-04). Uses FTS5 to narrow candidates, then
    rapidfuzz (WRatio) to score and rank them.
    """
    normalized = normalize_folder_name(folder_name)
    if not normalized:
        return []

    safe_tokens = [tok for tok in _NON_ALNUM_RE.sub(" ", normalized).split() if len(tok) >= 2]
    if not safe_tokens:
        return []
    # OR, not FTS5's implicit AND: one extra word in the folder name ("Season
    # 2", "Dub", a group name the normalizer didn't catch) would otherwise
    # rule out the right title entirely. Ranking by bm25 keeps the best
    # token overlaps inside the LIMIT; WRatio does the real scoring below.
    fts_query = " OR ".join(f'"{tok}"*' for tok in safe_tokens)
    result = await session.execute(
        text(
            "SELECT t.aid, t.title FROM anidb_title_fts f "
            "JOIN anidb_title_index t ON t.id = f.rowid "
            "WHERE anidb_title_fts MATCH :q ORDER BY f.rank LIMIT 500"
        ),
        {"q": fts_query},
    )
    rows = list(dict.fromkeys((row.aid, row.title) for row in result.all()))
    if not rows:
        return []

    # Scored as a list, not a {title: aid} dict: two different anime can
    # share a title (a remake and its original), and collapsing them would
    # hide exactly the ambiguity the top-2 check exists to catch.
    titles = [title for _, title in rows]
    scored = process.extract(
        normalized, titles, scorer=fuzz.WRatio, processor=fuzz_utils.default_process, limit=None
    )
    # One candidate per anime, its best-scoring title: several synonyms of the
    # *same* anime scoring close together is not ambiguity.
    best: dict[int, FuzzyCandidate] = {}
    for title, score, index in scored:
        aid = rows[index][0]
        if aid not in best or score > best[aid].score:
            best[aid] = FuzzyCandidate(aid=aid, title=title, score=score)
    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:limit]
