from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import animes, folders, tags
from app.api.animes import review_router
from app.api.deps import get_app_state, get_db
from app.api.errors import register_error_handlers
from app.config import Settings
from app.state import AppState


@pytest.fixture
def fake_state() -> AppState:
    scanner = MagicMock()
    scanner.full_scan_folder = AsyncMock()
    scanner.watch_folder = MagicMock()
    scanner.unwatch_folder = MagicMock()
    return AppState(
        settings=Settings(data_dir="/tmp/awp-test-unused"),
        event_bus=MagicMock(),
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
