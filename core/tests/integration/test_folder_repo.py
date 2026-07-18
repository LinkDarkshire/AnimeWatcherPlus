from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.models import Anime, AnimeProviderId, AnimeTag, ExpectedEpisode, JobLog, LocalEpisode, Tag
from app.db.repositories import AnimeRepo, FolderRepo, JobLogRepo, LocalEpisodeRepo


@pytest.mark.asyncio
async def test_delete_folder_with_animes_cascades(db_session) -> None:
    """Regression test: deleting a folder that still has Anime rows used to
    raise sqlite3.IntegrityError (FOREIGN KEY constraint failed) twice over:
    first because a bare `DELETE FROM folder` bypassed the ORM cascade
    entirely, then again because deleting the Anime rows themselves left
    JobLog entries (a foreign key to anime.id easy to miss) dangling. This
    exercises every table with a foreign key to anime.id at once so a future
    new one can't slip through unnoticed either.
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

    # Should not raise IntegrityError.
    await folder_repo.delete(folder.id)

    assert await folder_repo.get(folder.id) is None
    for model in (Anime, LocalEpisode, ExpectedEpisode, AnimeTag, AnimeProviderId, JobLog):
        column = model.anime_id if model is not Anime else Anime.id
        remaining = (
            await db_session.execute(select(model).where(column == anime.id))
        ).scalar_one_or_none()
        assert remaining is None, f"{model.__name__} row for the deleted anime was left behind"

    fts_row = await db_session.execute(
        text("SELECT 1 FROM anime_search_fts WHERE anime_id = :aid"), {"aid": anime.id}
    )
    assert fts_row.first() is None


@pytest.mark.asyncio
async def test_delete_empty_folder_still_works(db_session) -> None:
    folder_repo = FolderRepo(db_session)
    folder = await folder_repo.create("/tmp/awp-test-empty", "content", "Empty")
    await folder_repo.delete(folder.id)
    assert await folder_repo.get(folder.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_folder_is_a_noop(db_session) -> None:
    folder_repo = FolderRepo(db_session)
    await folder_repo.delete(999)  # must not raise
