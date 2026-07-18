from __future__ import annotations

import datetime as dt

from app.db.models import Anime, ExpectedEpisode
from app.services.staleness import is_stale, last_episode_air_date


def _anime(*, last_refresh: dt.datetime | None, air_dates: list[dt.date]) -> Anime:
    anime = Anime(folder_id=1, directory_path="/x", last_metadata_refresh=last_refresh)
    anime.expected_episodes = [ExpectedEpisode(ep_number=str(i), air_date=d) for i, d in enumerate(air_dates)]
    return anime


def test_last_episode_air_date_picks_max() -> None:
    anime = _anime(
        last_refresh=None,
        air_dates=[dt.date(2020, 1, 1), dt.date(2021, 6, 15), dt.date(2020, 12, 31)],
    )
    assert last_episode_air_date(anime) == dt.date(2021, 6, 15)


def test_last_episode_air_date_none_without_data() -> None:
    anime = _anime(last_refresh=None, air_dates=[])
    assert last_episode_air_date(anime) is None


def test_not_stale_when_never_refreshed() -> None:
    anime = _anime(last_refresh=None, air_dates=[dt.date(2015, 1, 1)])
    assert is_stale(anime, threshold_days=182) is False


def test_not_stale_without_air_date_data() -> None:
    anime = _anime(last_refresh=dt.datetime.now(dt.timezone.utc), air_dates=[])
    assert is_stale(anime, threshold_days=182) is False


def test_stale_when_gap_exceeds_threshold() -> None:
    last_air = dt.date(2020, 1, 1)
    refreshed = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)  # 366 days later
    anime = _anime(last_refresh=refreshed, air_dates=[last_air])
    assert is_stale(anime, threshold_days=182) is True


def test_not_stale_when_gap_within_threshold() -> None:
    last_air = dt.date(2020, 1, 1)
    refreshed = dt.datetime(2020, 3, 1, tzinfo=dt.timezone.utc)  # 60 days later
    anime = _anime(last_refresh=refreshed, air_dates=[last_air])
    assert is_stale(anime, threshold_days=182) is False
