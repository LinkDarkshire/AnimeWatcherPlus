from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger(__name__)

POSTER_FILENAME = "poster.jpg"
ANIINFO_FILENAME = "aniinfo.json"


async def download_poster(http_client: httpx.AsyncClient, poster_url: str, anime_dir: Path) -> str | None:
    """Downloads the AniDB poster straight into the anime's own folder (per
    user request, not a central app-data cache) as `poster.jpg` -- the
    filename Jellyfin/Kodi auto-detect as show artwork without needing an
    explicit NFO <thumb> reference (we add one anyway for clarity).
    Returns the filename on success so the caller can store it as the
    "we have a poster" marker, or None if the download failed.
    """
    try:
        # img7.anidb.net permanently redirects to cdn.anidb.net; httpx does
        # not follow redirects by default.
        response = await http_client.get(poster_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("poster_download_failed", url=poster_url)
        return None

    anime_dir.mkdir(parents=True, exist_ok=True)
    poster_path = anime_dir / POSTER_FILENAME
    poster_path.write_bytes(response.content)
    return POSTER_FILENAME


def write_aniinfo_json(
    anime_dir: Path,
    full_info: dict,
    *,
    episode_count_local: int,
    ident_status: str,
    match_score: float | None,
) -> Path:
    """Writes aniinfo.json: a superset of the Jellyfin-shaped tvshow.nfo,
    holding everything AniDB returned (all title variants, ratings, creators,
    related anime, full per-episode detail) plus this app's own bookkeeping
    (local vs. official episode count, identification confidence).
    """
    payload = dict(full_info)
    payload["local_library"] = {
        "episode_count_official": full_info.get("episode_count_official"),
        "episode_count_local": episode_count_local,
        "ident_status": ident_status,
        "match_score": match_score,
        "last_metadata_refresh": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    anime_dir.mkdir(parents=True, exist_ok=True)
    aniinfo_path = anime_dir / ANIINFO_FILENAME
    aniinfo_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return aniinfo_path
