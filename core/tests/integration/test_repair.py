from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import Anime, ExpectedEpisode, LocalEpisode
from app.db.repositories import AnimeRepo, FolderRepo
from app.providers.anidb import cache_dir
from app.services import artwork
from app.services.repair import run_repair_scan

pytestmark = pytest.mark.asyncio

CACHED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<anime id="4242" restricted="true">
    <type>OVA</type>
    <startdate>2016-08-26</startdate>
    <titles>
        <title xml:lang="x-jat" type="main">Tsundero</title>
        <title xml:lang="en" type="official">Tsundere Girl</title>
        <title xml:lang="ja" type="official">ツンデロ</title>
    </titles>
    <description>A short description.</description>
    <episodes>
        <episode id="1"><epno type="1">1</epno><title xml:lang="en">First</title><airdate>2016-08-26</airdate></episode>
        <episode id="2"><epno type="1">2</epno><title xml:lang="en">Second</title></episode>
    </episodes>
</anime>
"""


def _settings(tmp_path) -> Settings:
    settings = Settings(data_dir=tmp_path / "data")
    cache_dir(settings).mkdir(parents=True, exist_ok=True)
    return settings


async def _make_frozen_anime(session, folder_id, directory, **kwargs) -> Anime:
    """An anime the staleness rule froze out of rescans, still carrying the
    single untagged title an older cascade produced."""
    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = 4242
    anime.no_scan = True
    anime.title = "ツンデロ"
    for key, value in kwargs.items():
        setattr(anime, key, value)
    await session.commit()
    return anime


async def test_repair_scan_restores_everything_from_the_local_cache(db_session, tmp_path) -> None:
    settings = _settings(tmp_path)
    (cache_dir(settings) / "4242.xml").write_text(CACHED_XML, encoding="utf-8")
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    directory = tmp_path / "lib" / "Tsundero"
    anime = await _make_frozen_anime(db_session, folder.id, directory)
    (directory / artwork.POSTER_FILENAME).write_bytes(b"jpeg")
    db_session.add(
        LocalEpisode(
            anime_id=anime.id,
            file_path=str(directory / "Tsundero_02_ENG_www.UnderHentai.net.mkv"),
            ep_number=None,  # what the old parser left behind
        )
    )
    await db_session.commit()

    report = await run_repair_scan(db_session, settings)

    await db_session.refresh(anime)
    assert report.checked == 1
    assert report.titles_backfilled == 1
    assert report.titles_changed == 1
    assert report.metadata_filled == 1
    assert report.expected_episodes_added == 1
    assert report.posters_relinked == 1
    assert report.episode_numbers_fixed == 1
    assert report.without_local_source == 0

    # Display title now follows the configured order (English first).
    assert anime.title == "Tsundere Girl"
    assert (anime.title_main, anime.title_ja) == ("Tsundero", "ツンデロ")
    assert (anime.year, anime.media_type) == (2016, "OVA")
    assert anime.description == "A short description."
    assert anime.poster_path == artwork.POSTER_FILENAME
    assert anime.episode_count_expected == 2

    expected = (await db_session.execute(select(ExpectedEpisode))).scalars().all()
    assert sorted(e.ep_number for e in expected) == ["1", "2"]
    episode = (await db_session.execute(select(LocalEpisode))).scalar_one()
    assert episode.ep_number == "2"


async def test_repair_scan_covers_no_scan_anime(db_session, tmp_path) -> None:
    """The whole reason it exists: the normal rescan skips these entirely."""
    settings = _settings(tmp_path)
    (cache_dir(settings) / "4242.xml").write_text(CACHED_XML, encoding="utf-8")
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    anime = await _make_frozen_anime(db_session, folder.id, tmp_path / "lib" / "Tsundero")
    assert anime.no_scan is True

    await run_repair_scan(db_session, settings)

    await db_session.refresh(anime)
    assert anime.title == "Tsundere Girl"
    assert anime.no_scan is True  # repairing must not change the staleness verdict


async def test_repair_scan_falls_back_to_the_sidecar(db_session, tmp_path) -> None:
    settings = _settings(tmp_path)  # deliberately no cached response
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    directory = tmp_path / "lib" / "Tsundero"
    anime = await _make_frozen_anime(db_session, folder.id, directory)
    (directory / artwork.ANIINFO_FILENAME).write_text(
        json.dumps(
            {"titles": [{"language": "en", "type": "official", "value": "Tsundere Girl"}]}
        ),
        encoding="utf-8",
    )

    report = await run_repair_scan(db_session, settings)

    await db_session.refresh(anime)
    assert report.titles_backfilled == 1
    assert anime.title == "Tsundere Girl"


async def test_repair_scan_reports_what_it_cannot_repair(db_session, tmp_path) -> None:
    """No cached response and no sidecar -- only a full rescan can help, and
    the report has to say so instead of silently doing nothing."""
    settings = _settings(tmp_path)
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    anime = await _make_frozen_anime(db_session, folder.id, tmp_path / "lib" / "Tsundero")

    report = await run_repair_scan(db_session, settings)

    await db_session.refresh(anime)
    assert report.without_local_source == 1
    assert report.titles_backfilled == 0
    assert anime.title == "ツンデロ"  # left as it was rather than blanked


async def test_repair_scan_never_overwrites_existing_data(db_session, tmp_path) -> None:
    """It fills gaps. A year, description or hand-corrected episode number
    that is already there must survive."""
    settings = _settings(tmp_path)
    (cache_dir(settings) / "4242.xml").write_text(CACHED_XML, encoding="utf-8")
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    directory = tmp_path / "lib" / "Tsundero"
    anime = await _make_frozen_anime(
        db_session,
        folder.id,
        directory,
        year=1999,
        description="Mine",
        media_type="TV Series",
        original_title="Mine Too",
    )
    db_session.add(
        LocalEpisode(
            anime_id=anime.id,
            file_path=str(directory / "Tsundero_02_ENG.mkv"),
            ep_number="7",
            manual_override=True,
        )
    )
    await db_session.commit()

    report = await run_repair_scan(db_session, settings)

    await db_session.refresh(anime)
    assert report.metadata_filled == 0
    assert (anime.year, anime.description, anime.media_type) == (1999, "Mine", "TV Series")
    episode = (await db_session.execute(select(LocalEpisode))).scalar_one()
    assert episode.ep_number == "7"


async def test_repair_scan_is_idempotent(db_session, tmp_path) -> None:
    settings = _settings(tmp_path)
    (cache_dir(settings) / "4242.xml").write_text(CACHED_XML, encoding="utf-8")
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    await _make_frozen_anime(db_session, folder.id, tmp_path / "lib" / "Tsundero")

    await run_repair_scan(db_session, settings)
    second = await run_repair_scan(db_session, settings)

    assert second.titles_backfilled == 0
    assert second.titles_changed == 0
    assert second.metadata_filled == 0
    assert second.expected_episodes_added == 0
    assert second.episode_numbers_fixed == 0
