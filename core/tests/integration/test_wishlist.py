from __future__ import annotations

import gzip
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import animes
from app.api import wishlist as wishlist_api
from app.api.deps import get_app_state, get_db
from app.api.errors import register_error_handlers
from app.config import Settings
from app.db.models import WishlistEntry
from app.db.repositories import AnimeRepo, FolderRepo
from app.domain.metadata import AnimeMetadata, EpisodeInfo
from app.services import wishlist
from app.services.jobs import EventBus
from app.services.titledump import import_title_dump
from app.state import AppState


def _dump() -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><animetitles>'
        '<anime aid="100"><title xml:lang="x-jat" type="main">Shingeki no Kyojin</title>'
        '<title xml:lang="en" type="official">Attack on Titan</title>'
        '<title xml:lang="en" type="syn">AoT</title></anime>'
        '<anime aid="200"><title xml:lang="x-jat" type="main">Fate/Zero</title></anime>'
        "</animetitles>"
    )
    return gzip.compress(xml.encode("utf-8"))


@pytest.fixture
def state() -> AppState:
    return AppState(
        settings=Settings(data_dir="/tmp/awp-test-unused"),
        event_bus=EventBus(),
        job_queue=MagicMock(),
        provider_registry=MagicMock(),
        scanner=MagicMock(),
    )


@pytest.fixture
async def client(db_session, state):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(wishlist_api.router)
    app.include_router(animes.router)

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_app_state] = lambda: state
    await import_title_dump(db_session, _dump())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _library_anime(db_session, tmp_path, anidb_id: int) -> int:
    folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    directory = tmp_path / "content" / "Show"
    directory.mkdir(parents=True)
    anime = await AnimeRepo(db_session).create_pending(folder.id, str(directory), "Show")
    anime.anidb_id = anidb_id
    anime.ident_status = "identified"
    await db_session.commit()
    return anime.id


@pytest.mark.asyncio
async def test_search_returns_display_title_for_a_synonym_match(client) -> None:
    response = await client.get("/api/v1/wishlist/search", params={"q": "Attack on Titan"})

    assert response.status_code == 200
    first = response.json()[0]
    assert first["anidb_id"] == 100
    assert first["title"] == "Attack on Titan"  # default order: English first
    assert first["in_library"] is False
    assert first["on_wishlist"] is False


@pytest.mark.asyncio
async def test_search_by_anidb_id(client) -> None:
    response = await client.get("/api/v1/wishlist/search", params={"q": "200"})
    assert [c["anidb_id"] for c in response.json()] == [200]


@pytest.mark.asyncio
async def test_add_stores_entry_and_queues_details_fetch(client, state) -> None:
    response = await client.post("/api/v1/wishlist", json={"anidb_id": 100})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Attack on Titan"
    assert body["details_pending"] is True
    assert body["library_anime_id"] is None
    state.job_queue.enqueue.assert_called_once()
    assert state.job_queue.enqueue.call_args.args[0] == "wishlist_details"

    listed = (await client.get("/api/v1/wishlist")).json()
    assert [e["anidb_id"] for e in listed] == [100]
    flagged = (await client.get("/api/v1/wishlist/search", params={"q": "100"})).json()
    assert flagged[0]["on_wishlist"] is True


@pytest.mark.asyncio
async def test_add_rejects_duplicates_library_anime_and_unknown_ids(client, db_session, tmp_path) -> None:
    assert (await client.post("/api/v1/wishlist", json={"anidb_id": 100})).status_code == 201
    assert (await client.post("/api/v1/wishlist", json={"anidb_id": 100})).status_code == 409

    await _library_anime(db_session, tmp_path, 200)
    assert (await client.post("/api/v1/wishlist", json={"anidb_id": 200})).status_code == 409

    assert (await client.post("/api/v1/wishlist", json={"anidb_id": 999999})).status_code == 404


@pytest.mark.asyncio
async def test_wishlist_entries_never_show_up_in_the_library(client) -> None:
    await client.post("/api/v1/wishlist", json={"anidb_id": 100})

    library = (await client.get("/api/v1/animes")).json()
    assert library["total"] == 0


@pytest.mark.asyncio
async def test_entry_links_to_library_once_the_anime_arrives(client, db_session, tmp_path) -> None:
    await client.post("/api/v1/wishlist", json={"anidb_id": 100})
    anime_id = await _library_anime(db_session, tmp_path, 100)

    [entry] = (await client.get("/api/v1/wishlist")).json()
    assert entry["library_anime_id"] == anime_id


@pytest.mark.asyncio
async def test_remove(client) -> None:
    entry = (await client.post("/api/v1/wishlist", json={"anidb_id": 100})).json()

    assert (await client.delete(f"/api/v1/wishlist/{entry['id']}")).status_code == 204
    assert (await client.get("/api/v1/wishlist")).json() == []
    assert (await client.delete(f"/api/v1/wishlist/{entry['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_fetch_details_fills_year_type_and_regular_episode_count(test_engine, db_session, monkeypatch) -> None:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(wishlist, "session_scope", lambda: factory())
    await import_title_dump(db_session, _dump())
    entry = await wishlist.add(db_session, 100)

    registry = MagicMock()
    registry.fetch_chain = AsyncMock(
        return_value=(
            AnimeMetadata(
                external_id="100",
                title="Attack on Titan",
                title_en="Attack on Titan",
                title_main="Shingeki no Kyojin",
                year=2013,
                media_type="TV Series",
                episodes=[EpisodeInfo(ep_number=str(n)) for n in range(1, 26)]
                + [EpisodeInfo(ep_number="S1"), EpisodeInfo(ep_number="C1")],
            ),
            "anidb",
        )
    )
    events: list[dict] = []
    bus = EventBus()

    async def collect(payload: dict) -> None:
        events.append(payload)

    bus.subscribe(collect)

    await wishlist.fetch_details(entry.id, registry, bus)

    async with factory() as session:
        stored = await session.get(WishlistEntry, entry.id)
        assert (stored.year, stored.media_type, stored.episode_count) == (2013, "TV Series", 25)
        assert stored.details_fetched_at is not None
    assert [e["event"] for e in events] == ["wishlist.updated"]


@pytest.mark.asyncio
async def test_fetch_details_failure_leaves_entry_pending(test_engine, db_session, monkeypatch) -> None:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(wishlist, "session_scope", lambda: factory())
    await import_title_dump(db_session, _dump())
    entry = await wishlist.add(db_session, 200)

    registry = MagicMock()
    registry.fetch_chain = AsyncMock(return_value=(None, None))  # e.g. ban cool-down

    await wishlist.fetch_details(entry.id, registry, EventBus())

    [item] = await wishlist.list_items(db_session)
    assert item.details_pending is True
    assert item.title == "Fate/Zero"
