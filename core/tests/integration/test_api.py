from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import (
    animes,
    folders,
    maintenance,
    pending_actions,
    rename_queue,
    settings_api,
    sort_queue,
    tags,
)
from app.api.animes import review_router
from app.api.deps import get_app_state, get_db
from app.api.errors import register_error_handlers
from app.config import Settings
from app.services import pending_actions as pending_actions_service
from app.services.jobs import EventBus
from app.state import AppState


@pytest.fixture
def fake_state() -> AppState:
    scanner = MagicMock()
    scanner.full_scan_folder = AsyncMock()
    scanner.watch_folder = MagicMock()
    scanner.unwatch_folder = MagicMock()
    return AppState(
        settings=Settings(data_dir="/tmp/awp-test-unused"),
        event_bus=EventBus(),
        job_queue=MagicMock(),
        provider_registry=MagicMock(),
        scanner=scanner,
    )


@pytest.fixture
def app(db_session, fake_state) -> FastAPI:
    test_app = FastAPI()
    register_error_handlers(test_app)
    test_app.include_router(folders.router)
    test_app.include_router(animes.router)
    test_app.include_router(animes.public_router)
    test_app.include_router(review_router)
    test_app.include_router(tags.router)
    test_app.include_router(sort_queue.router)
    test_app.include_router(rename_queue.router)
    test_app.include_router(pending_actions.router)
    test_app.include_router(settings_api.router)
    test_app.include_router(maintenance.router)

    test_app.dependency_overrides[get_db] = _make_db_override(db_session)
    test_app.dependency_overrides[get_app_state] = lambda: fake_state
    return test_app


def _make_db_override(session):
    async def _override():
        yield session

    return _override


@pytest.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_and_list_folders(client, tmp_path, fake_state) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    response = await client.post(
        "/api/v1/folders", json={"path": str(content_dir), "type": "content", "name": "Content"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["path"] == str(content_dir)
    fake_state.scanner.watch_folder.assert_called_once()
    fake_state.job_queue.enqueue.assert_called_once()
    assert fake_state.job_queue.enqueue.call_args[0][0] == "scan"

    response = await client.get("/api/v1/folders")
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_create_folder_rejects_nonexistent_path(client) -> None:
    response = await client.post(
        "/api/v1/folders", json={"path": "/does/not/exist", "type": "content", "name": "x"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_folder_rejects_duplicate(client, tmp_path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    payload = {"path": str(content_dir), "type": "content", "name": "Content"}
    first = await client.post("/api/v1/folders", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/folders", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_list_animes_empty(client) -> None:
    response = await client.get("/api/v1/animes")
    assert response.status_code == 200
    assert response.json() == {"total": 0, "page": 1, "items": []}


@pytest.mark.asyncio
async def test_get_anime_not_found(client) -> None:
    response = await client.get("/api/v1/animes/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_tags_empty(client) -> None:
    response = await client.get("/api/v1/tags")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_anime_poster_not_found_without_poster(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await AnimeRepo(db_session).create_pending(folder.id, str(tmp_path / "Show A"), "Show A")

    response = await client.get(f"/api/v1/animes/{anime.id}/poster")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_anime_poster_serves_local_file(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo
    from app.services.artwork import POSTER_FILENAME

    anime_dir = tmp_path / "Show A"
    anime_dir.mkdir()
    (anime_dir / POSTER_FILENAME).write_bytes(b"fake-jpeg-bytes")

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder.id, str(anime_dir), "Show A")
    await anime_repo.set_poster_path(anime.id, POSTER_FILENAME)

    response = await client.get(f"/api/v1/animes/{anime.id}/poster")
    assert response.status_code == 200
    assert response.content == b"fake-jpeg-bytes"
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_anime_list_and_detail_expose_poster_url_when_present(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo
    from app.services.artwork import POSTER_FILENAME

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder.id, str(tmp_path / "Show A"), "Show A")
    await anime_repo.set_poster_path(anime.id, POSTER_FILENAME)

    list_response = await client.get("/api/v1/animes")
    assert list_response.json()["items"][0]["poster_path"] == f"/api/v1/animes/{anime.id}/poster"

    detail_response = await client.get(f"/api/v1/animes/{anime.id}")
    assert detail_response.json()["poster_path"] == f"/api/v1/animes/{anime.id}/poster"


@pytest.mark.asyncio
async def test_rescan_all_delegates_to_scanner_ignoring_staleness(client, fake_state) -> None:
    fake_state.scanner.enqueue_metadata_rescan = AsyncMock(return_value=3)

    response = await client.post("/api/v1/animes/rescan-all")

    assert response.status_code == 200
    assert response.json() == {"queued": 3}
    fake_state.scanner.enqueue_metadata_rescan.assert_awaited_once_with(ignore_staleness=True)


@pytest.mark.asyncio
async def test_delete_anime_removes_it(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await AnimeRepo(db_session).create_pending(folder.id, str(tmp_path / "Show A"), "Show A")

    response = await client.delete(f"/api/v1/animes/{anime.id}")
    assert response.status_code == 204

    assert (await client.get(f"/api/v1/animes/{anime.id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_anime_not_found(client) -> None:
    response = await client.delete("/api/v1/animes/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_duplicates_empty(client) -> None:
    response = await client.get("/api/v1/duplicates")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_duplicates_groups_by_anidb_id(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime_repo = AnimeRepo(db_session)
    dir_a = tmp_path / "Show Copy A"
    dir_a.mkdir()
    dir_b = tmp_path / "Show Copy B"
    dir_b.mkdir()
    anime_a = await anime_repo.create_pending(folder.id, str(dir_a), "Show Copy A")
    anime_b = await anime_repo.create_pending(folder.id, str(dir_b), "Show Copy B")
    anime_a.title = "Same Show"
    anime_a.anidb_id = 123
    anime_b.title = "Same Show"
    anime_b.anidb_id = 123
    await db_session.commit()

    response = await client.get("/api/v1/duplicates")
    assert response.status_code == 200
    groups = response.json()
    assert len(groups) == 1
    assert groups[0]["anidb_id"] == 123
    assert groups[0]["title"] == "Same Show"
    paths = {entry["directory_path"] for entry in groups[0]["entries"]}
    assert paths == {str(dir_a), str(dir_b)}


@pytest.mark.asyncio
async def test_delete_empty_dir_success(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    empty_dir = content_dir / "Empty Show"
    empty_dir.mkdir()
    (empty_dir / "readme.txt").write_bytes(b"no videos")

    folder = await FolderRepo(db_session).create(str(content_dir), "content", "Content")

    response = await client.post(
        f"/api/v1/folders/{folder.id}/delete-empty-dir", json={"path": str(empty_dir)}
    )
    assert response.status_code == 204
    assert not empty_dir.exists()


@pytest.mark.asyncio
async def test_delete_empty_dir_rejects_path_traversal(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    folder = await FolderRepo(db_session).create(str(content_dir), "content", "Content")

    response = await client.post(
        f"/api/v1/folders/{folder.id}/delete-empty-dir", json={"path": str(outside_dir)}
    )
    assert response.status_code == 400
    assert outside_dir.exists()


@pytest.mark.asyncio
async def test_delete_empty_dir_rejects_when_no_longer_empty(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    show_dir = content_dir / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(db_session).create(str(content_dir), "content", "Content")

    response = await client.post(
        f"/api/v1/folders/{folder.id}/delete-empty-dir", json={"path": str(show_dir)}
    )
    assert response.status_code == 409
    assert show_dir.exists()


async def _make_identified_download_anime(session, folder_id, directory, anidb_id, ep_numbers):
    from app.db.models import ExpectedEpisode
    from app.db.repositories import AnimeRepo, LocalEpisodeRepo

    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = directory.name
    anime.title_main = directory.name
    for ep in ep_numbers:
        session.add(ExpectedEpisode(anime_id=anime.id, ep_number=str(ep)))
    await session.commit()

    episode_repo = LocalEpisodeRepo(session)
    for ep in ep_numbers:
        file_path = directory / f"{directory.name} - {ep:02d}.mkv"
        file_path.write_bytes(b"x")
        await episode_repo.upsert(anime.id, str(file_path), 1, file_path.stat().st_mtime, str(ep))
    return anime


@pytest.mark.asyncio
async def test_resolve_sort_success(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_identified_download_anime(
        db_session, download_folder.id, tmp_path / "downloads" / "Show A", 1, [1]
    )

    response = await client.post(
        f"/api/v1/sort-queue/{anime.id}/resolve", json={"target_folder_id": content_folder.id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["moved"] == 1
    assert body["unmatched"] == 0
    assert (tmp_path / "content" / "Show A" / "Show A - S01E01 - Episode 1.mkv").exists()


@pytest.mark.asyncio
async def test_resolve_sort_unknown_anime_404(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    response = await client.post(
        "/api/v1/sort-queue/999/resolve", json={"target_folder_id": content_folder.id}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_sort_source_not_in_download_folder_400(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    other_content_folder = await FolderRepo(db_session).create(str(tmp_path / "content2"), "content", "Content 2")
    anime = await _make_identified_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Show B", 2, [1]
    )

    response = await client.post(
        f"/api/v1/sort-queue/{anime.id}/resolve", json={"target_folder_id": other_content_folder.id}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_resolve_sort_target_not_content_folder_400(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    other_download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads2"), "download", "Downloads 2")
    anime = await _make_identified_download_anime(
        db_session, download_folder.id, tmp_path / "downloads" / "Show C", 3, [1]
    )

    response = await client.post(
        f"/api/v1/sort-queue/{anime.id}/resolve", json={"target_folder_id": other_download_folder.id}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_resolve_sort_nothing_matches_409(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo, LocalEpisodeRepo

    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    directory = tmp_path / "downloads" / "Show D"
    directory.mkdir(parents=True)
    anime = await AnimeRepo(db_session).create_pending(download_folder.id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = 4
    await db_session.commit()
    file_path = directory / "unknown.mkv"
    file_path.write_bytes(b"a")
    await LocalEpisodeRepo(db_session).upsert(anime.id, str(file_path), 1, file_path.stat().st_mtime, None)

    response = await client.post(
        f"/api/v1/sort-queue/{anime.id}/resolve", json={"target_folder_id": content_folder.id}
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_sort_queue_endpoint(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    await _make_identified_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show E", 5, [1, 2])

    response = await client.get("/api/v1/sort-queue")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["episode_count"] == 2
    assert body[0]["matched_count"] == 2


@pytest.mark.asyncio
async def test_delete_empty_dir_unknown_folder(client, tmp_path) -> None:
    response = await client.post(
        "/api/v1/folders/999/delete-empty-dir", json={"path": str(tmp_path / "x")}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_rename_success(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_identified_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Show A", 1, [1]
    )
    # Mismatched title so the directory itself also needs renaming.
    anime.title = "Renamed Show"
    anime.title_main = "Renamed Show"
    await db_session.commit()

    response = await client.post(f"/api/v1/rename-queue/{anime.id}/resolve")
    assert response.status_code == 200
    body = response.json()
    assert body["renamed_dir"] is True
    assert body["renamed_files"] == 1
    assert (tmp_path / "content" / "Renamed Show" / "Renamed Show - S01E01 - Episode 1.mkv").exists()


@pytest.mark.asyncio
async def test_resolve_rename_unknown_anime_404(client) -> None:
    response = await client.post("/api/v1/rename-queue/999/resolve")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_rename_directory_collision_409(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    (tmp_path / "content" / "Renamed Show").mkdir(parents=True)
    anime = await _make_identified_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Show B", 2, [1]
    )
    anime.title = "Renamed Show"
    anime.title_main = "Renamed Show"
    await db_session.commit()

    response = await client.post(f"/api/v1/rename-queue/{anime.id}/resolve")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_rename_queue_endpoint(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_identified_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Show C", 3, [1]
    )
    anime.title = "Renamed Show C"
    anime.title_main = "Renamed Show C"
    await db_session.commit()

    response = await client.get("/api/v1/rename-queue")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["current_dir_name"] == "Show C"
    assert body[0]["target_dir_name"] == "Renamed Show C"


@pytest.mark.asyncio
async def test_pending_actions_count_sums_all_queues(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo

    response = await client.get("/api/v1/pending-actions/count")
    assert response.status_code == 200
    assert response.json()["total"] == 0

    # A review-queue item (needs_manual_id).
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    review_dir = tmp_path / "content" / "Needs Review"
    review_dir.mkdir(parents=True)
    await AnimeRepo(db_session).create_pending(content_folder.id, str(review_dir), "Needs Review")
    review_anime = await AnimeRepo(db_session).get_by_directory(str(review_dir))
    review_anime.ident_status = "needs_manual_id"
    await db_session.commit()

    # A rename-queue item.
    rename_anime = await _make_identified_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Show D", 4, [1]
    )
    rename_anime.title = "Renamed Show D"
    rename_anime.title_main = "Renamed Show D"
    await db_session.commit()

    # The total is cached in-process. In production every write above would
    # have gone through the scanner or an event that drops the cache; this
    # test writes rows straight through the repos, so it has to say so.
    pending_actions_service.invalidate()

    response = await client.get("/api/v1/pending-actions/count")
    assert response.status_code == 200
    assert response.json()["total"] == 2


@pytest.mark.asyncio
async def test_put_settings_normalizes_a_partial_title_order(client) -> None:
    response = await client.put("/api/v1/settings", json={"values": {"display_title_order": ["ja"]}})

    assert response.status_code == 200
    assert response.json()["values"]["display_title_order"] == ["ja", "en", "main"]


@pytest.mark.asyncio
async def test_put_settings_reapplies_display_titles_to_existing_anime(
    client, db_session, tmp_path
) -> None:
    """Changing the order has to rewrite the already-stored display names, not
    just affect future identifications -- the library list is sorted and
    searched by that column."""
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    directory = tmp_path / "content" / "Show"
    directory.mkdir(parents=True)
    anime = await AnimeRepo(db_session).create_pending(folder.id, str(directory), "Show")
    anime.anidb_id = 900
    anime.ident_status = "identified"
    anime.title = "English Title"
    anime.title_main = "Romaji Title"
    anime.title_en = "English Title"
    await db_session.commit()

    response = await client.put(
        "/api/v1/settings", json={"values": {"display_title_order": ["main", "en", "ja"]}}
    )
    assert response.status_code == 200

    await db_session.refresh(anime)
    assert anime.title == "Romaji Title"


@pytest.mark.asyncio
async def test_put_settings_leaves_unrelated_keys_untouched(client) -> None:
    response = await client.put("/api/v1/settings", json={"values": {"sort_mode": "auto"}})

    assert response.status_code == 200
    assert response.json()["values"]["sort_mode"] == "auto"


async def _make_series_with_gap(session, folder_id: int, directory, anidb_id: int):
    """Identified series expecting episodes 1-3 but only holding 1 and 3."""
    from app.db.models import ExpectedEpisode, LocalEpisode
    from app.db.repositories import AnimeRepo

    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = directory.name
    anime.title_main = directory.name
    for number in ("1", "2", "3"):
        session.add(ExpectedEpisode(anime_id=anime.id, ep_number=number, title=f"Ep {number}"))
    for number in ("1", "3"):
        session.add(
            LocalEpisode(
                anime_id=anime.id, file_path=f"{directory}/ep{number}.mkv", ep_number=number
            )
        )
    await session.commit()
    return anime


@pytest.mark.asyncio
async def test_anime_list_exposes_completeness(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 700)

    body = (await client.get("/api/v1/animes")).json()

    assert body["items"][0]["completeness"] == {"expected": 3, "present": 2, "missing": 1}


@pytest.mark.asyncio
async def test_anime_list_missing_filter(client, db_session, tmp_path) -> None:
    from app.db.models import ExpectedEpisode, LocalEpisode
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    incomplete = await _make_series_with_gap(db_session, folder.id, tmp_path / "Gap", 701)

    complete_dir = tmp_path / "Complete"
    complete_dir.mkdir()
    complete = await AnimeRepo(db_session).create_pending(folder.id, str(complete_dir), "Complete")
    complete.ident_status = "identified"
    complete.anidb_id = 702
    complete.title = "Complete"
    db_session.add(ExpectedEpisode(anime_id=complete.id, ep_number="1"))
    db_session.add(
        LocalEpisode(anime_id=complete.id, file_path=str(complete_dir / "1.mkv"), ep_number="1")
    )
    await db_session.commit()

    assert (await client.get("/api/v1/animes")).json()["total"] == 2
    filtered = (await client.get("/api/v1/animes?missing=true")).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == incomplete.id


@pytest.mark.asyncio
async def test_missing_episodes_per_anime(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 703)

    response = await client.get(f"/api/v1/animes/{anime.id}/missing-episodes")

    assert response.status_code == 200
    assert response.json() == {
        "anime_id": anime.id,
        "expected": 3,
        "present": 2,
        "missing": [{"ep_number": "2", "title": "Ep 2", "air_date": None}],
    }


@pytest.mark.asyncio
async def test_missing_episodes_unknown_anime_404(client) -> None:
    assert (await client.get("/api/v1/animes/999/missing-episodes")).status_code == 404


@pytest.mark.asyncio
async def test_missing_episodes_overview(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 704)

    body = (await client.get("/api/v1/missing-episodes")).json()

    assert body["total"] == 1
    assert body["items"][0]["anime_id"] == anime.id
    assert body["items"][0]["missing"] == 1
    assert body["items"][0]["present"] == 2


@pytest.mark.asyncio
async def test_manual_episode_number_correction_closes_the_gap(client, db_session, tmp_path) -> None:
    """The whole point of the correction: a file whose number the parser got
    wrong stops being reported as a missing episode once fixed."""
    from app.db.models import LocalEpisode
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 705)
    # The file for episode 2 is there, but its number was never parsed.
    db_session.add(
        LocalEpisode(anime_id=anime.id, file_path=str(tmp_path / "Show A" / "weird.mkv"), ep_number=None)
    )
    await db_session.commit()

    episodes = (await client.get(f"/api/v1/animes/{anime.id}/episodes")).json()
    unparsed = next(e for e in episodes if e["ep_number"] is None)
    assert unparsed["manual_override"] is False

    patched = await client.patch(
        f"/api/v1/animes/{anime.id}/episodes/{unparsed['id']}", json={"ep_number": "2"}
    )
    assert patched.status_code == 200
    assert patched.json()["manual_override"] is True

    body = (await client.get(f"/api/v1/animes/{anime.id}/missing-episodes")).json()
    assert body["missing"] == []
    assert body["present"] == 3


@pytest.mark.asyncio
async def test_manual_episode_number_can_be_cleared(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 706)
    episodes = (await client.get(f"/api/v1/animes/{anime.id}/episodes")).json()

    await client.patch(
        f"/api/v1/animes/{anime.id}/episodes/{episodes[0]['id']}", json={"ep_number": "9"}
    )
    cleared = await client.patch(
        f"/api/v1/animes/{anime.id}/episodes/{episodes[0]['id']}", json={"ep_number": None}
    )

    assert cleared.status_code == 200
    assert cleared.json()["ep_number"] is None
    assert cleared.json()["manual_override"] is False


@pytest.mark.asyncio
async def test_manual_episode_number_rejects_non_numeric(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 707)
    episodes = (await client.get(f"/api/v1/animes/{anime.id}/episodes")).json()

    response = await client.patch(
        f"/api/v1/animes/{anime.id}/episodes/{episodes[0]['id']}", json={"ep_number": "S1"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_episode_patch_rejects_foreign_episode(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show A", 708)
    other = await _make_series_with_gap(db_session, folder.id, tmp_path / "Show B", 709)
    foreign = (await client.get(f"/api/v1/animes/{other.id}/episodes")).json()[0]

    response = await client.patch(
        f"/api/v1/animes/{anime.id}/episodes/{foreign['id']}", json={"ep_number": "1"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_anime_pending_actions_lists_the_rename_with_its_files(client, db_session, tmp_path) -> None:
    """The series page shows exactly what a rename would do, file by file,
    before the user confirms it there."""
    from app.db.repositories import FolderRepo

    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_identified_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Old Name", 800, [1, 2]
    )
    anime.title = "Real Title"
    anime.title_main = "Real Title"
    await db_session.commit()

    body = (await client.get(f"/api/v1/animes/{anime.id}/pending-actions")).json()

    assert body["sort"] is None  # content folder: nothing to sort
    rename = body["rename"]
    assert rename["current_dir_name"] == "Old Name"
    assert rename["target_dir_name"] == "Real Title"
    assert rename["dir_needs_rename"] is True
    assert [f["target"] for f in rename["file_renames"]] == [
        "Real Title - S01E01 - Episode 1.mkv",
        "Real Title - S01E02 - Episode 2.mkv",
    ]


@pytest.mark.asyncio
async def test_anime_pending_actions_lists_a_pending_sort(client, db_session, tmp_path) -> None:
    from app.db.repositories import FolderRepo

    download_folder = await FolderRepo(db_session).create(str(tmp_path / "dl"), "download", "Downloads")
    anime = await _make_identified_download_anime(
        db_session, download_folder.id, tmp_path / "dl" / "Show", 801, [1, 2]
    )

    body = (await client.get(f"/api/v1/animes/{anime.id}/pending-actions")).json()

    assert body["sort"] == {"episode_count": 2, "matched_count": 2, "suggested_target_folder_id": None}


@pytest.mark.asyncio
async def test_anime_pending_actions_empty_when_nothing_is_open(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await AnimeRepo(db_session).create_pending(folder.id, str(tmp_path / "Show"), "Show")

    body = (await client.get(f"/api/v1/animes/{anime.id}/pending-actions")).json()

    assert body == {"rename": None, "sort": None}


@pytest.mark.asyncio
async def test_anime_pending_actions_unknown_anime_404(client) -> None:
    assert (await client.get("/api/v1/animes/999/pending-actions")).status_code == 404


@pytest.mark.asyncio
async def test_review_queue_is_alphabetical(client, db_session, tmp_path) -> None:
    from app.db.repositories import AnimeRepo, FolderRepo

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    for name in ("zebra", "Apple", "mango"):
        anime = await AnimeRepo(db_session).create_pending(folder.id, str(tmp_path / name), name)
        anime.ident_status = "needs_manual_id"
    await db_session.commit()

    body = (await client.get("/api/v1/review-queue")).json()

    assert [item["title_guess"] for item in body] == ["Apple", "mango", "zebra"]


@pytest.mark.asyncio
async def test_repair_scan_endpoint_reports_what_it_changed(
    client, db_session, tmp_path, fake_state
) -> None:
    """The settings button's contract: it returns actual counts, so the user
    sees whether anything was wrong rather than just "done"."""
    from app.db.repositories import AnimeRepo, FolderRepo
    from app.providers.anidb import cache_dir

    fake_state.settings = Settings(data_dir=tmp_path / "data")
    cache_dir(fake_state.settings).mkdir(parents=True)
    (cache_dir(fake_state.settings) / "4242.xml").write_text(
        """<anime id="4242"><type>OVA</type><titles>
            <title xml:lang="x-jat" type="main">Tsundero</title>
            <title xml:lang="en" type="official">Tsundere Girl</title>
        </titles></anime>""",
        encoding="utf-8",
    )
    folder = await FolderRepo(db_session).create(str(tmp_path / "lib"), "content", "Content")
    directory = tmp_path / "lib" / "Tsundero"
    directory.mkdir(parents=True)
    anime = await AnimeRepo(db_session).create_pending(folder.id, str(directory), "Tsundero")
    anime.ident_status = "identified"
    anime.anidb_id = 4242
    anime.no_scan = True
    anime.title = "ツンデロ"
    await db_session.commit()

    response = await client.post("/api/v1/maintenance/repair-scan")

    assert response.status_code == 200
    body = response.json()
    assert body["checked"] == 1
    assert body["titles_backfilled"] == 1
    assert body["titles_changed"] == 1
    assert body["without_local_source"] == 0

    await db_session.refresh(anime)
    assert anime.title == "Tsundere Girl"
