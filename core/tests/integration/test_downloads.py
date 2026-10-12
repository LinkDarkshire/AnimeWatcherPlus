from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import ClassVar
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
    DownloadClient,
    DownloadClientError,
    DownloadStatus,
    NothingFound,
    SearchQuery,
    SearchResult,
    SearchSource,
    SearchSourceError,
    SeriesHit,
    TwoStageSearchSource,
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

    assert {"qbittorrent", "jdownloader", "example_link_list", "example_link_file"} <= set(registry.classes)
    assert registry.builtin_ids == {"qbittorrent", "transmission", "jdownloader", "myjdownloader"}
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


class _TwoStage(TwoStageSearchSource):
    id = "two_stage"
    name = "TwoStage"

    async def search_series(self, query: SearchQuery) -> list[SeriesHit]:
        return [SeriesHit(title="Show", url="https://site/show/"), SeriesHit(title="Show OVA", url="https://site/ova/")]

    async def list_releases(self, series: SeriesHit, query: SearchQuery) -> list[SearchResult]:
        return [
            SearchResult(
                title=f"{series.title} {query.episode}",
                link="https://short/x",
                hoster="MEGA",
                details={"Format": "MKV"},
                needs_browser=True,
            )
        ]


@pytest.mark.asyncio
async def test_two_stage_source_offers_series_then_lists_releases(client, db_session, tmp_path, state) -> None:
    state.download_plugins.register(_TwoStage)
    anime_id = await _anime_with_episodes(db_session, tmp_path, "Show", 9, [(1, None)])
    source = (await client.post("/api/v1/downloads/integrations", json={"plugin_id": "two_stage", "name": "TS"})).json()

    searched = (await client.post("/api/v1/downloads/search", json={"anime_id": anime_id, "episode": 1})).json()
    assert searched["results"] == []
    assert [s["title"] for s in searched["series"]] == ["Show", "Show OVA"]
    assert searched["series"][0]["integration_id"] == source["id"]

    picked = searched["series"][1]
    releases = (
        await client.post(
            "/api/v1/downloads/releases",
            json={
                "anime_id": anime_id,
                "episode": 1,
                "integration_id": picked["integration_id"],
                "series": {"title": picked["title"], "url": picked["url"]},
            },
        )
    ).json()
    [release] = releases["results"]
    assert release["title"] == "Show OVA 1"
    assert release["needs_browser"] is True
    assert release["details"] == {"Format": "MKV"} and release["hoster"] == "MEGA"


class _ProgressClient(DownloadClient):
    id = "progress_client"
    name = "Progress"
    statuses: ClassVar[dict] = {}

    def accepts(self, link: str) -> bool:
        return True

    async def add(self, link: str, *, destination: str | None, package_name: str) -> str | None:
        return f"h-{link}"

    async def status(self, handles: list[str]) -> dict:
        return {h: s for h, s in self.statuses.items() if h in handles}


class _NothingSource(TwoStageSearchSource):
    id = "nothing_source"
    name = "Nothing"

    async def search_series(self, query: SearchQuery) -> list[SeriesHit]:
        raise NothingFound("Nichts gefunden -- gesucht nach: „A“")

    async def list_releases(self, series: SeriesHit, query: SearchQuery) -> list[SearchResult]:
        return []


@pytest.mark.asyncio
async def test_nothing_found_is_a_note_not_an_error(client, db_session, tmp_path, state) -> None:
    state.download_plugins.register(_NothingSource)
    anime_id = await _anime_with_episodes(db_session, tmp_path, "Show", 9, [(1, None)])
    await client.post("/api/v1/downloads/integrations", json={"plugin_id": "nothing_source", "name": "N"})

    body = (await client.post("/api/v1/downloads/search", json={"anime_id": anime_id, "episode": 1})).json()

    assert body["errors"] == {}
    assert body["notes"] == {"N": "Nichts gefunden -- gesucht nach: „A“"}


@pytest.mark.asyncio
async def test_active_downloads_show_live_status_and_can_be_hidden(client, db_session, tmp_path, state) -> None:
    state.download_plugins.register(_ProgressClient)
    _ProgressClient.statuses = {"h-https://x/1": DownloadStatus("downloading", 0.5, 2048, 30)}
    anime_id = await _anime_with_episodes(db_session, tmp_path, "Show", 9, [(1, None), (2, None)])
    progress = (await client.post("/api/v1/downloads/integrations", json={"plugin_id": "progress_client", "name": "P"})).json()
    watch = tmp_path / "fw"
    watch.mkdir()
    jd = (
        await client.post(
            "/api/v1/downloads/integrations",
            json={"plugin_id": "jdownloader", "name": "JD", "config": {"watch_folder": str(watch)}},
        )
    ).json()

    for client_id, link, episode in ((progress["id"], "https://x/1", 1), (progress["id"], "https://x/2", 2), (jd["id"], "https://x/3", 2)):
        sent = await client.post(
            "/api/v1/downloads/send",
            json={"client_id": client_id, "link": link, "anime_id": anime_id, "episode": episode},
        )
        assert sent.status_code == 200

    active = (await client.get("/api/v1/downloads/active")).json()
    by_link = {a["title"] + "|" + a["client_name"]: a["status"] for a in active}
    assert by_link["Show - 01|P"] == {
        "state": "downloading", "progress": 0.5, "speed_bps": 2048, "eta_seconds": 30, "message": None
    }
    assert by_link["Show - 02|P"]["state"] == "unknown"  # client no longer knows it
    assert by_link["Show - 02|JD"]["message"] == "Dieser Client meldet keinen Fortschritt"

    first = next(a for a in active if a["title"] == "Show - 01")
    assert (await client.post(f"/api/v1/downloads/requests/{first['request_id']}/dismiss")).status_code == 204
    remaining = (await client.get("/api/v1/downloads/active")).json()
    assert first["request_id"] not in {a["request_id"] for a in remaining}


@pytest.mark.asyncio
@respx.mock
async def test_qbittorrent_tags_downloads_and_reads_their_status() -> None:
    add = respx.post("http://qb:8080/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Ok."))
    client = QBittorrentClient({"url": "http://qb:8080"})

    tag = await client.add("magnet:?xt=1", destination=None, package_name="Show")
    assert tag and tag.startswith("awp-") and tag in add.calls.last.request.content.decode()

    respx.get("http://qb:8080/api/v2/torrents/info", params={"tag": tag}).mock(
        return_value=httpx.Response(
            200, json=[{"state": "downloading", "progress": 0.4, "dlspeed": 500, "eta": 8640000}]
        )
    )
    respx.get("http://qb:8080/api/v2/torrents/info", params={"tag": "awp-gone"}).mock(
        return_value=httpx.Response(200, json=[])
    )
    statuses = await client.status([tag, "awp-gone"])
    assert (statuses[tag].state, statuses[tag].progress, statuses[tag].eta_seconds) == ("downloading", 0.4, None)
    assert "awp-gone" not in statuses
