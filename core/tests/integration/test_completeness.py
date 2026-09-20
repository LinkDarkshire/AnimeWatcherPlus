from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.db.completeness import CompletenessRepo
from app.db.models import Anime, ExpectedEpisode, LocalEpisode
from app.db.repositories import AnimeRepo, FolderRepo, LocalEpisodeRepo
from app.services import sorter

pytestmark = pytest.mark.asyncio


async def _make_anime(
    session,
    folder_id: int,
    directory,
    *,
    anidb_id: int,
    expected: list[str],
    local: list[str | None],
    title: str | None = None,
) -> Anime:
    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = title or directory.name
    for number in expected:
        session.add(ExpectedEpisode(anime_id=anime.id, ep_number=number, title=f"Ep {number}"))
    for index, number in enumerate(local):
        session.add(
            LocalEpisode(anime_id=anime.id, file_path=f"{directory}/{index}.mkv", ep_number=number)
        )
    await session.commit()
    return anime


async def test_completeness_counts_missing_episodes(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session, folder.id, tmp_path / "A", anidb_id=1,
        expected=["1", "2", "3", "4"], local=["1", "3", "4"],
    )

    result = (await CompletenessRepo(db_session).for_animes([anime.id]))[anime.id]

    assert (result.expected, result.present, result.missing) == (4, 3, 1)
    assert result.is_complete is False


async def test_completeness_normalizes_zero_padding(db_session, tmp_path) -> None:
    """Local numbers come from filename parsing and aren't padded like AniDB's
    -- "05" and "5" have to count as the same episode, exactly as
    sorter._normalize_ep_number treats them."""
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session, folder.id, tmp_path / "A", anidb_id=1, expected=["5"], local=["05"]
    )

    assert (await CompletenessRepo(db_session).for_animes([anime.id]))[anime.id].missing == 0


async def test_completeness_ignores_specials(db_session, tmp_path) -> None:
    """AniDB numbers specials/credits/trailers S1/C1/T1. The local filename
    parser never produces those, so counting them would report every series as
    permanently incomplete."""
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session, folder.id, tmp_path / "A", anidb_id=1,
        expected=["1", "2", "S1", "C1"], local=["1", "2"],
    )

    result = (await CompletenessRepo(db_session).for_animes([anime.id]))[anime.id]

    assert (result.expected, result.present, result.missing) == (2, 2, 0)


async def test_completeness_agrees_with_the_sorter_matching(db_session, tmp_path) -> None:
    """The SQL comparison and the Python matching used for sorting/renaming
    must never disagree about which episodes exist."""
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session, folder.id, tmp_path / "A", anidb_id=1,
        expected=["1", "02", "3", "S1"], local=["1", "3", None, "99"],
    )

    reloaded = await AnimeRepo(db_session).get(anime.id)
    local_episodes = await LocalEpisodeRepo(db_session).by_anime(anime.id)
    matches = sorter.match_local_episodes(local_episodes, reloaded.expected_episodes)
    matched_numbers = {
        sorter._normalize_ep_number(expected.ep_number) for _, expected in matches if expected
    }

    result = (await CompletenessRepo(db_session).for_animes([anime.id]))[anime.id]

    assert result.present == len(matched_numbers)
    assert result.expected == 3  # "1", "02" and "3"; the special doesn't count
    assert result.missing == 1  # episode 2 has no file


async def test_missing_for_anime_lists_episodes_in_order(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session, folder.id, tmp_path / "A", anidb_id=1,
        expected=["10", "2", "1"], local=["1"],
    )
    episode_two = (
        await db_session.execute(
            select(ExpectedEpisode).where(
                ExpectedEpisode.anime_id == anime.id, ExpectedEpisode.ep_number == "2"
            )
        )
    ).scalar_one()
    episode_two.air_date = dt.date(2024, 2, 18)
    await db_session.commit()

    missing = await CompletenessRepo(db_session).missing_for_anime(anime.id)

    # Numeric order, not the order the provider listed them in.
    assert [m.ep_number for m in missing] == ["2", "10"]
    assert missing[0].title == "Ep 2"
    assert missing[0].air_date == dt.date(2024, 2, 18)


async def test_list_incomplete_excludes_complete_and_unidentified(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    incomplete = await _make_anime(
        db_session, folder.id, tmp_path / "Incomplete", anidb_id=1,
        expected=["1", "2"], local=["1"], title="Incomplete",
    )
    await _make_anime(
        db_session, folder.id, tmp_path / "Complete", anidb_id=2,
        expected=["1"], local=["1"], title="Complete",
    )
    # A movie: one expected episode, present -- nothing missing, so it never
    # shows up without needing a media-type special case.
    await _make_anime(
        db_session, folder.id, tmp_path / "Movie", anidb_id=3,
        expected=["1"], local=["1"], title="Movie",
    )
    pending = await _make_anime(
        db_session, folder.id, tmp_path / "Pending", anidb_id=4,
        expected=["1", "2"], local=[], title="Pending",
    )
    pending.ident_status = "pending"
    await db_session.commit()

    rows, total = await CompletenessRepo(db_session).list_incomplete(page=1, size=50)

    assert total == 1
    assert [(a.id, missing) for a, missing in rows] == [(incomplete.id, 1)]


async def test_list_incomplete_paginates(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    for i in range(5):
        await _make_anime(
            db_session, folder.id, tmp_path / f"Show {i}", anidb_id=100 + i,
            expected=["1", "2"], local=["1"], title=f"Show {i}",
        )

    page1, total = await CompletenessRepo(db_session).list_incomplete(page=1, size=2)
    page3, _ = await CompletenessRepo(db_session).list_incomplete(page=3, size=2)

    assert total == 5
    assert [a.title for a, _ in page1] == ["Show 0", "Show 1"]
    assert [a.title for a, _ in page3] == ["Show 4"]


async def test_search_missing_only_filter(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    incomplete = await _make_anime(
        db_session, folder.id, tmp_path / "Incomplete", anidb_id=1,
        expected=["1", "2"], local=["1"], title="Incomplete",
    )
    await _make_anime(
        db_session, folder.id, tmp_path / "Complete", anidb_id=2,
        expected=["1"], local=["1"], title="Complete",
    )

    repo = AnimeRepo(db_session)
    all_items, all_total = await repo.search(
        query=None, year=None, media_type=None, tag=None, status_filter=None, page=1, size=50
    )
    missing_items, missing_total = await repo.search(
        query=None, year=None, media_type=None, tag=None, status_filter=None, page=1, size=50,
        missing_only=True,
    )

    assert all_total == 2
    assert missing_total == 1
    assert [a.id for a in missing_items] == [incomplete.id]
    assert len(all_items) == 2
