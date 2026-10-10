from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import downloads as downloads_api
from app.api.deps import get_app_state, get_db
from app.api.errors import register_error_handlers
from app.config import Settings
from app.db.models import DownloadRequest, ExpectedEpisode, LocalEpisode, WishlistEntry
from app.db.repositories import AnimeRepo, FolderRepo
from app.downloads import (
    DownloadClientError,
    SearchQuery,
    SearchResult,
    SearchSource,
    SearchSourceError,
)
from app.downloads.clients.jdownloader import JDownloaderClient
from app.downloads.clients.qbittorrent import QBittorrentClient
from app.downloads.registry import build_registry
from app.downloads.service import wanted
from app.services.jobs import EventBus
from app.state import AppState

EXAMPLES = Path(__file__).resolve().parents[2] / "plugin_examples"


# --- Plugin loading ------------------------------------------------------------------


def test_registry_loads_example_plugins_and_reports_broken_files(tmp_path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    for example in EXAMPLES.glob("*.py"):
        shutil.copy(example, plugins / example.name)
    (plugins / "kaputt.py").write_text("this is not python(", encoding="utf-8")
    (plugins / "leer.py").write_text("x = 1\n", encoding="utf-8")
    (plugins / "_privat.py").write_text("raise RuntimeError('never imported')\n", encoding="utf-8")

    registry = build_registry(plugins)

    assert {"qbittorrent", "jdownloader", "beispiel_linkliste", "beispiel_linkdatei"} <= set(registry.classes)
    assert registry.builtin_ids == {"qbittorrent", "jdownloader"}
    assert {e.file for e in registry.load_errors} == {"kaputt.py", "leer.py"}
    assert (plugins / "LIESMICH.txt").exists()


def test_duplicate_plugin_id_is_a_load_error(tmp_path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "dup.py").write_text(
        "from app.downloads import DownloadClient\n"
        "class Dup(DownloadClient):\n"
        "    id = 'qbittorrent'\n"
        "    name = 'Dup'\n"
        "    def accepts(self, link): return True\n"
        "    async def add(self, link, *, destination, package_name): pass\n",
        encoding="utf-8",
    )
    registry = build_registry(plugins)
    assert registry.classes["qbittorrent"] is QBittorrentClient
    assert [e.file for e in registry.load_errors] == ["dup.py"]


# --- Built-in clients ----------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_qbittorrent_logs_in_and_adds_with_save_path() -> None:
    login = respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Ok."))
    add = respx.post("http://qb:8080/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Ok."))

    client = QBittorrentClient({"url": "http://qb:8080/", "username": "u", "password": "p", "category": "anime"})
    await client.add("magnet:?xt=urn:btih:abc", destination="/downloads", package_name="Show - 01")
    await client.close()

    assert login.called
    body = add.calls.last.request.content.decode()
    assert "magnet:?xt=urn:btih:abc" in body
    assert "/downloads" in body and "anime" in body


@pytest.mark.asyncio
@respx.mock
async def test_qbittorrent_save_path_override_and_errors() -> None:
    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Fails."))
    client = QBittorrentClient({"url": "http://qb:8080", "username": "u", "password": "wrong"})
    with pytest.raises(DownloadClientError, match="Anmeldung"):
        await client.test_connection()

    add = respx.post("http://qb:8080/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Ok."))
    no_auth = QBittorrentClient({"url": "http://qb:8080", "save_path": "/nas/downloads"})
    await no_auth.add("https://x/download.php?id=1", destination="Z:\\downloads", package_name="Show")
    assert "/nas/downloads" in add.calls.last.request.content.decode()
    assert no_auth.accepts("magnet:?xt=1") and not no_auth.accepts("ftp://x")


@pytest.mark.asyncio
async def test_jdownloader_writes_complete_crawljob(tmp_path) -> None:
    watch = tmp_path / "folderwatch"
    watch.mkdir()
    client = JDownloaderClient({"watch_folder": str(watch), "auto_start": True})

    await client.test_connection()
    await client.add("https://host/file.mkv", destination="/downloads", package_name="Show\n - 01")

    [job] = list(watch.glob("*.crawljob"))
    assert list(watch.iterdir()) == [job]  # no temp file or test probe left
    content = job.read_text(encoding="utf-8").splitlines()
    assert "text=https://host/file.mkv" in content
    assert "packageName=Show  - 01" in content  # line break neutralized
    assert "downloadFolder=/downloads" in content
    assert "autoStart=TRUE" in content
    assert not client.accepts("magnet:?xt=1")


@pytest.mark.asyncio
async def test_jdownloader_missing_watch_folder(tmp_path) -> None:
    client = JDownloaderClient({"watch_folder": str(tmp_path / "missing")})
    with pytest.raises(DownloadClientError):
        await client.add("https://x", destination=None, package_name="x")


# --- What's wanted -----------------------------------------------------------------


async def _anime_with_episodes(session, tmp_path, name, anidb_id, episodes, have=()):
    folder = await FolderRepo(session).create(str(tmp_path / name), "content", name)
    directory = tmp_path / name / name
    directory.mkdir(parents=True)
    anime = await AnimeRepo(session).create_pending(folder.id, str(directory), name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = name
    for number, air_date in episodes:
        session.add(ExpectedEpisode(anime_id=anime.id, ep_number=str(number), air_date=air_date))
    for number in have:
        session.add(LocalEpisode(anime_id=anime.id, file_path=str(directory / f"{number}.mkv"), ep_number=str(number)))
    await session.commit()
    return anime.id


@pytest.mark.asyncio
async def test_wanted_lists_only_aired_missing_episodes(db_session, tmp_path) -> None:
    today = dt.date(2026, 10, 10)
    past, future = dt.date(2026, 1, 1), dt.date(2026, 12, 1)
    airing = await _anime_with_episodes(
        db_session, tmp_path, "Airing", 1,
        [(1, past), (2, None), (3, past), (4, future), (5, None)],
        have=[1],
    )
    undated = await _anime_with_episodes(db_session, tmp_path, "Old Show", 2, [(1, None), (2, None)])
    await _anime_with_episodes(db_session, tmp_path, "Complete", 3, [(1, past)], have=[1])
    db_session.add(WishlistEntry(anidb_id=50, title="Wished"))
    db_session.add(WishlistEntry(anidb_id=1, title="Already here"))  # now in the library
    await db_session.commit()

    result = await wanted(db_session, today=today)

    by_id = {a.anime_id: [e.ep_number for e in a.episodes] for a in result.missing}
    # 2: undated gap before an aired episode; 4 and 5: not out yet.
    assert by_id == {airing: ["2", "3"], undated: ["1", "2"]}
    assert [w.title for w in result.wishlist] == ["Wished"]


# --- API -----------------------------------------------------------------------------


class _FakeSource(SearchSource):
    id = "fake_source"
    name = "Fake"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        return [SearchResult(title=f"{query.titles[0]} {query.episode}", link="https://x/ep.torrent")]


class _BrokenSource(SearchSource):
    id = "broken_source"
    name = "Broken"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        raise SearchSourceError("Indexer offline")


@pytest.fixture
def state(tmp_path) -> AppState:
    registry = build_registry(None)
    registry.register(_FakeSource)
    registry.register(_BrokenSource)
    return AppState(
        settings=Settings(data_dir=str(tmp_path / "data")),
        event_bus=EventBus(),
        job_queue=MagicMock(),
        provider_registry=MagicMock(),
        scanner=MagicMock(),
        download_plugins=registry,
    )


@pytest.fixture
async def client(db_session, state):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(downloads_api.router)

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_app_state] = lambda: state
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_integration_crud_never_returns_passwords(client) -> None:
    created = await client.post(
        "/api/v1/downloads/integrations",
        json={"plugin_id": "qbittorrent", "name": "NAS", "config": {"url": "http://qb", "password": "secret"}},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "client"
    assert "password" not in body["config"] and body["secrets_set"] == ["password"]

    # Saving without re-entering the password keeps it.
    updated = await client.put(
        f"/api/v1/downloads/integrations/{body['id']}",
        json={"name": "NAS", "enabled": True, "config": {"url": "http://qb2", "password": ""}},
    )
    assert updated.json()["config"]["url"] == "http://qb2"
    assert updated.json()["secrets_set"] == ["password"]

    missing_required = await client.post(
        "/api/v1/downloads/integrations", json={"plugin_id": "jdownloader", "name": "JD", "config": {}}
    )
    assert missing_required.status_code == 422

    plugins = (await client.get("/api/v1/downloads/plugins")).json()
    assert {p["id"] for p in plugins["plugins"]} >= {"qbittorrent", "jdownloader", "fake_source"}


@pytest.mark.asyncio
async def test_search_collects_results_and_per_source_errors(client, db_session, tmp_path) -> None:
    anime_id = await _anime_with_episodes(db_session, tmp_path, "Show", 9, [(1, None)])
    for plugin_id, name in (("fake_source", "Fake"), ("broken_source", "Broken")):
        await client.post("/api/v1/downloads/integrations", json={"plugin_id": plugin_id, "name": name})

    response = await client.post("/api/v1/downloads/search", json={"anime_id": anime_id, "episode": 1})

    body = response.json()
    assert [(r["source_name"], r["title"]) for r in body["results"]] == [("Fake", "Show 1")]
    assert body["errors"] == {"Broken": "Indexer offline"}


@pytest.mark.asyncio
async def test_send_hands_link_to_client_and_records_request(client, db_session, tmp_path) -> None:
    watch = tmp_path / "folderwatch"
    watch.mkdir()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    await FolderRepo(db_session).create(str(downloads_dir), "download", "Downloads")
    anime_id = await _anime_with_episodes(db_session, tmp_path, "Show", 9, [(1, None)])
    jd = (
        await client.post(
            "/api/v1/downloads/integrations",
            json={"plugin_id": "jdownloader", "name": "JD", "config": {"watch_folder": str(watch)}},
        )
    ).json()

    sent = await client.post(
        "/api/v1/downloads/send",
        json={"client_id": jd["id"], "link": "https://host/ep1.mkv", "anime_id": anime_id, "episode": 1},
    )
    assert sent.status_code == 200
    assert sent.json() == {"title": "Show - 01", "client_name": "JD"}
    [job] = list(watch.glob("*.crawljob"))
    assert f"downloadFolder={downloads_dir}" in job.read_text(encoding="utf-8")

    rejected = await client.post(
        "/api/v1/downloads/send",
        json={"client_id": jd["id"], "link": "magnet:?xt=1", "anime_id": anime_id, "episode": 1},
    )
    assert rejected.status_code == 422  # JDownloader doesn't take torrents

    wanted_now = (await client.get("/api/v1/downloads/wanted")).json()
    [episode] = wanted_now["missing"][0]["episodes"]
    assert episode["last_request"]["client_name"] == "JD"
    rows = (await db_session.execute(DownloadRequest.__table__.select())).all()
    assert len(rows) == 1
