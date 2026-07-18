from __future__ import annotations

import datetime as dt

from app.db.models import Anime


def last_episode_air_date(anime: Anime) -> dt.date | None:
    dates = [ep.air_date for ep in anime.expected_episodes if ep.air_date is not None]
    return max(dates) if dates else None


def is_stale(anime: Anime, threshold_days: float) -> bool:
    """An anime counts as stale once it's been refreshed *after* its last known
    episode aired, and that refresh already happened long enough ago that a
    new episode almost certainly isn't coming (no data -> never stale, since
    there's nothing to judge staleness against; keep refreshing it)."""
    if anime.last_metadata_refresh is None:
        return False
    last_air = last_episode_air_date(anime)
    if last_air is None:
        return False
    gap_days = (anime.last_metadata_refresh.date() - last_air).days
    return gap_days > threshold_days
