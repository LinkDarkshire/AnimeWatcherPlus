from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.models import AnimeProviderId, AnimeTag, ExpectedEpisode, JobLog, LocalEpisode, Tag
from app.db.repositories import AnimeRepo, FolderRepo, JobLogRepo, LocalEpisodeRepo


@pytest.mark.asyncio
async def test_delete_anime_cascades_child_rows(db_session) -> None:
    """Mirrors test_folder_repo's cascade regression test, but for deleting a
    single anime directly (the "confirmed duplicate, remove one" flow) --
    AnimeRepo.delete() previously only cleaned up the FTS mirror row, so any
    anime with tags/episodes/provider-ids/job-log entries would hit
    `FOREIGN KEY constraint failed` the first time this was actually called.
    """
    folder_repo = FolderRepo(db_session)
    anime_repo = AnimeRepo(db_session)
    episode_repo = LocalEpisodeRepo(db_session)
    job_log_repo = JobLogRepo(db_session)

    folder = await folder_repo.create("/tmp/awp-test-content", "content", "Content")
    anime = await anime_repo.create_pending(folder.id, "/tmp/awp-test-content/Show A", "Show A")
    await episode_repo.upsert(anime.id, "/tmp/awp-test-content/Show A/ep1.mkv", 100, 1.0, "1")

    tag = Tag(name="isekai")
    db_session.add(tag)
    await db_session.flush()
    db_session.add(AnimeTag(anime_id=anime.id, tag_id=tag.id, weight=500))
    db_session.add(ExpectedEpisode(anime_id=anime.id, ep_number="1", title="Pilot"))
    db_session.add(AnimeProviderId(anime_id=anime.id, provider="anidb", external_id="123"))
    await db_session.commit()
    await job_log_repo.add("identify", "identified", "anidb_id=123", anime.id)

    await anime_repo.delete(anime.id)  # must not raise IntegrityError

    assert await anime_repo.get(anime.id) is None
    for model in (LocalEpisode, ExpectedEpisode, AnimeTag, AnimeProviderId, JobLog):
        remaining = (
            await db_session.execute(select(model).where(model.anime_id == anime.id))
        ).scalar_one_or_none()
        assert remaining is None, f"{model.__name__} row for the deleted anime was left behind"

    fts_row = await db_session.execute(
        text("SELECT 1 FROM anime_search_fts WHERE anime_id = :aid"), {"aid": anime.id}
    )
    assert fts_row.first() is None


@pytest.mark.asyncio
async def test_delete_nonexistent_anime_is_a_noop(db_session) -> None:
    await AnimeRepo(db_session).delete(999)  # must not raise


@pytest.mark.asyncio
async def test_delete_one_duplicate_clears_flag_on_the_survivor(db_session) -> None:
    """A duplicate group of 2: deleting one entry must leave the other no
    longer flagged as a duplicate (there's nothing left to duplicate)."""
    folder_repo = FolderRepo(db_session)
    anime_repo = AnimeRepo(db_session)
    folder = await folder_repo.create("/tmp/awp-test-content", "content", "Content")

    anime_a = await anime_repo.create_pending(folder.id, "/tmp/awp-test-content/A", "A")
    anime_b = await anime_repo.create_pending(folder.id, "/tmp/awp-test-content/B", "B")
    anime_a.anidb_id = 42
    anime_b.anidb_id = 42
    await db_session.commit()
    await anime_repo.recompute_duplicate_flags(42)

    reloaded_b_before = await anime_repo.get(anime_b.id)
    assert reloaded_b_before.is_duplicate is True

    await anime_repo.delete(anime_a.id)

    reloaded_b_after = await anime_repo.get(anime_b.id)
    assert reloaded_b_after.is_duplicate is False
    assert reloaded_b_after.duplicate_of_anime_id is None


@pytest.mark.asyncio
async def test_delete_one_of_three_duplicates_keeps_the_remaining_two_flagged(db_session) -> None:
    folder_repo = FolderRepo(db_session)
    anime_repo = AnimeRepo(db_session)
    folder = await folder_repo.create("/tmp/awp-test-content", "content", "Content")

    animes = [
        await anime_repo.create_pending(folder.id, f"/tmp/awp-test-content/{name}", name)
        for name in ("A", "B", "C")
    ]
    for a in animes:
        a.anidb_id = 7
    await db_session.commit()
    await anime_repo.recompute_duplicate_flags(7)

    await anime_repo.delete(animes[0].id)

    groups = await anime_repo.list_duplicate_groups()
    assert len(groups) == 1
    _, remaining = groups[0]
    assert {a.id for a in remaining} == {animes[1].id, animes[2].id}
    assert sum(1 for a in remaining if a.is_duplicate) == 1  # one primary, one flagged


@pytest.mark.asyncio
async def test_list_duplicate_groups_ignores_unique_anidb_ids(db_session) -> None:
    folder_repo = FolderRepo(db_session)
    anime_repo = AnimeRepo(db_session)
    folder = await folder_repo.create("/tmp/awp-test-content", "content", "Content")

    solo = await anime_repo.create_pending(folder.id, "/tmp/awp-test-content/Solo", "Solo")
    solo.anidb_id = 1
    dup_a = await anime_repo.create_pending(folder.id, "/tmp/awp-test-content/DupA", "DupA")
    dup_b = await anime_repo.create_pending(folder.id, "/tmp/awp-test-content/DupB", "DupB")
    dup_a.anidb_id = 2
    dup_b.anidb_id = 2
    await db_session.commit()

    groups = await anime_repo.list_duplicate_groups()
    assert len(groups) == 1
    anidb_id, entries = groups[0]
    assert anidb_id == 2
    assert {a.id for a in entries} == {dup_a.id, dup_b.id}


@pytest.mark.asyncio
async def test_recompute_duplicate_flags_noop_for_missing_anidb_id(db_session) -> None:
    await AnimeRepo(db_session).recompute_duplicate_flags(None)  # must not raise
