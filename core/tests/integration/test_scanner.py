from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Anime, Base, ExpectedEpisode, Setting
from app.db.repositories import AnimeRepo, FolderRepo
from app.db.session import _set_sqlite_pragma
from app.providers.base import ProviderRegistry
from app.services.jobs import EventBus, JobQueue
from app.services.scanner import ScannerService, _directory_signature, anime_dir_for, is_ignored
from app.services.settings_store import STALENESS_RULE_ENABLED


def test_is_ignored() -> None:
    from pathlib import Path

    assert is_ignored(Path("movie.mkv.part"))
    assert is_ignored(Path("movie.mkv.crdownload"))
    assert not is_ignored(Path("movie.mkv"))


def test_anime_dir_for() -> None:
    from pathlib import Path

    root = Path("/library")
    assert anime_dir_for(Path("/library/Show A/ep1.mkv"), root) == Path("/library/Show A")
    assert anime_dir_for(Path("/other/Show A/ep1.mkv"), root) is None
    assert anime_dir_for(root, root) is None


def test_directory_signature_changes_with_new_file(tmp_path) -> None:
    d = tmp_path / "anime"
    d.mkdir()
    (d / "a.mkv").write_bytes(b"x" * 100)
    sig1 = _directory_signature(d)
    (d / "b.mkv").write_bytes(b"y" * 50)
    sig2 = _directory_signature(d)
    assert sig1 != sig2


@pytest_asyncio.fixture
async def scanner_env(tmp_path, monkeypatch):
    """The scanner's background job queue opens its own DB sessions concurrently
    with foreground test assertions. An in-memory StaticPool connection can't
    safely serve two independently-checked-out sessions at once (SQLite raises
    "no active connection"), so this uses a real temp-file SQLite DB instead --
    same as production, where every session_scope() call gets its own connection.
    """
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("CREATE VIRTUAL TABLE anime_search_fts USING fts5(anime_id UNINDEXED, title, alt_titles_text)")
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.services.scanner as scanner_module

    monkeypatch.setattr(scanner_module, "session_scope", lambda: factory())

    settings = Settings(data_dir="/tmp/awp-test-unused", scan_debounce_interval_s=0.05, scan_debounce_checks=2)
    event_bus = EventBus()
    job_queue = JobQueue(event_bus)
    job_queue.start()
    registry = ProviderRegistry()
    service = ScannerService(settings, registry, event_bus, job_queue)

    async with factory() as session:
        yield service, session

    await job_queue.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_scan_discovers_anime_dirs(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    (root / "Show A").mkdir()
    (root / "Show A" / "ep1.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "content", "Content")

    await scanner.full_scan_folder(folder)

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    animes = result.scalars().all()
    assert len(animes) == 1
    assert animes[0].directory_path == str(root / "Show A")


@pytest.mark.asyncio
async def test_scan_aborts_gracefully_if_folder_deleted_mid_scan(scanner_env, tmp_path) -> None:
    """Regression test: a background scan job can still be running (or a
    live-watch debounce task still pending) when the user deletes the
    folder. Trying to INSERT a new Anime row against the now-nonexistent
    folder_id used to raise sqlite3.IntegrityError instead of aborting
    cleanly.
    """
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_bytes(b"x" * 10)

    folder_repo = FolderRepo(session)
    folder = await folder_repo.create(str(root), "content", "Content")

    # Simulate the race: the folder is deleted while a scan for it is
    # already in flight (the caller's `folder` object is now stale).
    await folder_repo.delete(folder.id)

    # Must not raise, and must not insert an Anime row for the deleted folder.
    await scanner._process_anime_dir(folder, show_dir)

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_rescan_skips_unchanged_files(scanner_env, tmp_path, monkeypatch) -> None:
    """NFA-03 scan-cache: a second scan over an untouched directory must not
    re-upsert files it already knows about (mtime/size unchanged)."""
    import app.services.scanner as scanner_module

    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "content", "Content")

    original_upsert = scanner_module.LocalEpisodeRepo.upsert
    call_count = 0

    async def counting_upsert(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original_upsert(self, *args, **kwargs)

    monkeypatch.setattr(scanner_module.LocalEpisodeRepo, "upsert", counting_upsert)

    await scanner.full_scan_folder(folder)
    assert call_count == 1

    await scanner.full_scan_folder(folder)
    assert call_count == 1  # unchanged file -> no second upsert


@pytest.mark.asyncio
async def test_rescan_reparses_unchanged_file_with_stale_episode_number(scanner_env, tmp_path) -> None:
    """The size/mtime cache must not freeze a number an older parser got
    wrong: in a real library 675 files had kept a NULL episode number from
    before the underscore-separated-name fix and showed up as missing
    episodes, although nothing about the files themselves had changed."""
    from app.db.models import LocalEpisode

    scanner, session = scanner_env
    root = tmp_path / "content"
    show_dir = root / "Tsundero"
    show_dir.mkdir(parents=True)
    (show_dir / "Tsundero_03_ENG_www.UnderHentai.net.mkv").write_bytes(b"x" * 10)
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    await scanner.full_scan_folder(folder)
    episode = (await session.execute(select(LocalEpisode))).scalar_one()
    episode.ep_number = None  # what the old parser had stored
    await session.commit()

    await scanner.full_scan_folder(folder)

    await session.refresh(episode)
    assert episode.ep_number == "3"


@pytest.mark.asyncio
async def test_rescan_never_overwrites_a_manual_episode_number(scanner_env, tmp_path) -> None:
    from app.db.models import LocalEpisode

    scanner, session = scanner_env
    root = tmp_path / "content"
    show_dir = root / "Show A"
    show_dir.mkdir(parents=True)
    (show_dir / "Show A - 01.mkv").write_bytes(b"x" * 10)
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    await scanner.full_scan_folder(folder)
    episode = (await session.execute(select(LocalEpisode))).scalar_one()
    episode.ep_number = "7"
    episode.manual_override = True
    await session.commit()

    await scanner.full_scan_folder(folder)

    await session.refresh(episode)
    assert episode.ep_number == "7"


@pytest.mark.asyncio
async def test_full_scan_deletes_removed_anime(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "content", "Content")
    await scanner.full_scan_folder(folder)

    import shutil

    shutil.rmtree(show_dir)

    await scanner.full_scan_folder(folder)

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_handle_removed_deletes_anime_immediately(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "content", "Content")
    await scanner.full_scan_folder(folder)

    import shutil

    shutil.rmtree(show_dir)

    await scanner._handle_removed(show_dir)

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_new_empty_dir_is_not_added_and_publishes_event(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    show_dir = root / "Empty Show"
    show_dir.mkdir()
    (show_dir / "readme.txt").write_bytes(b"no videos here")

    folder = await FolderRepo(session).create(str(root), "content", "Content")

    events: list[dict] = []

    async def collect(payload: dict) -> None:
        events.append(payload)

    scanner._event_bus.subscribe(collect)

    await scanner.full_scan_folder(folder)

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    assert result.scalars().all() == []

    empty_events = [p["data"] for p in events if p["event"] == "folder.empty_dir_found"]
    assert len(empty_events) == 1
    assert empty_events[0]["folder_id"] == folder.id
    assert empty_events[0]["path"] == str(show_dir)


@pytest.mark.asyncio
async def test_new_dir_with_video_is_added_as_usual(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "content", "Content")
    await scanner.full_scan_folder(folder)

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    animes = result.scalars().all()
    assert len(animes) == 1
    assert animes[0].directory_path == str(show_dir)


@pytest.mark.asyncio
async def test_debounce_waits_for_stable_directory(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    show_dir = root / "Show A"
    show_dir.mkdir()
    (show_dir / "ep1.mkv.part").write_bytes(b"x" * 10)

    await scanner._debounce(folder, show_dir)
    await asyncio.sleep(0.02)
    (show_dir / "ep1.mkv.part").rename(show_dir / "ep1.mkv")
    await scanner._debounce(folder, show_dir)

    animes: list[Anime] = []
    for _ in range(50):
        result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
        animes = result.scalars().all()
        if animes:
            break
        await asyncio.sleep(0.05)

    assert len(animes) == 1


async def _make_identified_anime(
    session, folder_id: int, directory, anidb_id: int, refreshed_at, last_air_date
) -> Anime:
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.last_metadata_refresh = refreshed_at
    # Assigning straight to the `expected_episodes` relationship attribute on
    # an already-persisted object triggers a lazy-load of the existing
    # collection first (to diff against), which is a sync, unawaited DB
    # round-trip on an AsyncSession -> MissingGreenlet. Adding the child row
    # directly and refreshing afterwards avoids that path entirely.
    session.add(ExpectedEpisode(anime_id=anime.id, ep_number="1", air_date=last_air_date))
    await session.commit()
    await session.refresh(anime, attribute_names=["expected_episodes"])
    return anime


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_skips_stale_anime(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    fresh_dir = root / "Fresh Show"
    fresh_dir.mkdir()
    stale_dir = root / "Stale Show"
    stale_dir.mkdir()

    await _make_identified_anime(session, folder.id, fresh_dir, 1, now, now.date())
    await _make_identified_anime(
        session, folder.id, stale_dir, 2, now, (now - dt.timedelta(days=400)).date()
    )

    enqueued_types: list[str] = []
    scanner._job_queue.enqueue = lambda job_type, factory: enqueued_types.append(job_type)

    count = await scanner.enqueue_metadata_rescan(ignore_staleness=False)

    assert count == 1
    assert enqueued_types == ["rescan"]


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_ignore_staleness_includes_everything(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    stale_dir = root / "Stale Show"
    stale_dir.mkdir()
    await _make_identified_anime(
        session, folder.id, stale_dir, 2, now, (now - dt.timedelta(days=400)).date()
    )

    enqueued_types: list[str] = []
    scanner._job_queue.enqueue = lambda job_type, factory: enqueued_types.append(job_type)

    count = await scanner.enqueue_metadata_rescan(ignore_staleness=True)

    assert count == 1


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_respects_global_rule_toggle(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    stale_dir = root / "Stale Show"
    stale_dir.mkdir()
    await _make_identified_anime(
        session, folder.id, stale_dir, 2, now, (now - dt.timedelta(days=400)).date()
    )
    session.add(Setting(key=STALENESS_RULE_ENABLED, value=False))
    await session.commit()

    enqueued_types: list[str] = []
    scanner._job_queue.enqueue = lambda job_type, factory: enqueued_types.append(job_type)

    count = await scanner.enqueue_metadata_rescan(ignore_staleness=False)

    assert count == 1  # rule globally disabled -> stale anime included too


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_persists_no_scan_for_newly_stale_anime(
    scanner_env, tmp_path
) -> None:
    """The whole point of the `no_scan` column: once an anime is found
    stale, that verdict must survive so the *next* startup can skip it
    without recomputing is_stale() (or hitting AniDB) at all."""
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    stale_dir = root / "Stale Show"
    stale_dir.mkdir()
    stale_anime = await _make_identified_anime(
        session, folder.id, stale_dir, 2, now, (now - dt.timedelta(days=400)).date()
    )
    assert stale_anime.no_scan is False

    stale_anime_id = stale_anime.id  # captured before expire_all() below
    scanner._job_queue.enqueue = lambda job_type, factory: None
    await scanner.enqueue_metadata_rescan(ignore_staleness=False)

    # The scanner writes through its own session (via session_scope(), a
    # separate connection to the same temp-file DB) -- this session's
    # identity map won't see that commit's new column values until expired.
    # (expire_all() expires *every* attribute, including the PK, so it must
    # run after anything that reads plain, unawaited attributes off objects
    # already in this session -- otherwise the next such access tries to
    # lazily reload outside a valid async context and raises MissingGreenlet.)
    session.expire_all()
    reloaded = await AnimeRepo(session).get(stale_anime_id)
    assert reloaded.no_scan is True


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_skips_already_flagged_no_scan_without_recomputing(
    scanner_env, tmp_path
) -> None:
    """An anime already persisted as no_scan must be skipped outright, even
    if a fresh is_stale() computation would (for whatever reason, e.g. the
    threshold setting changed) say it's not stale anymore -- the persisted
    verdict is sticky until an explicit full rescan clears it."""
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    show_dir = root / "Flagged Show"
    show_dir.mkdir()
    # A *fresh* air date -- is_stale() would say False if recomputed.
    anime = await _make_identified_anime(session, folder.id, show_dir, 3, now, now.date())
    anime.no_scan = True
    await session.commit()

    enqueued_types: list[str] = []
    scanner._job_queue.enqueue = lambda job_type, factory: enqueued_types.append(job_type)

    count = await scanner.enqueue_metadata_rescan(ignore_staleness=False)

    assert count == 0
    assert enqueued_types == []


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_ignore_staleness_still_includes_no_scan_anime(
    scanner_env, tmp_path
) -> None:
    """Force Full Scan re-checks every identified anime against AniDB
    regardless of no_scan (unchanged) -- but per user request, the scanner
    itself must not clear the flag as a side effect of doing so. Only an
    explicit AniDB-ID change (identification.py) may ever un-flag one."""
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    stale_dir = root / "Stale Show"
    stale_dir.mkdir()
    anime = await _make_identified_anime(
        session, folder.id, stale_dir, 2, now, (now - dt.timedelta(days=400)).date()
    )
    anime.no_scan = True
    await session.commit()
    anime_id = anime.id  # captured before expire_all() below

    enqueued_types: list[str] = []
    scanner._job_queue.enqueue = lambda job_type, factory: enqueued_types.append(job_type)

    count = await scanner.enqueue_metadata_rescan(ignore_staleness=True)

    assert count == 1
    assert enqueued_types == ["rescan"]
    session.expire_all()
    reloaded = await AnimeRepo(session).get(anime_id)
    assert reloaded.no_scan is True  # the scanner itself never clears it


@pytest.mark.asyncio
async def test_enqueue_metadata_rescan_rule_disabled_still_includes_no_scan_anime(
    scanner_env, tmp_path
) -> None:
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    now = dt.datetime.now(dt.timezone.utc)
    stale_dir = root / "Stale Show"
    stale_dir.mkdir()
    anime = await _make_identified_anime(
        session, folder.id, stale_dir, 2, now, (now - dt.timedelta(days=400)).date()
    )
    anime.no_scan = True
    session.add(Setting(key=STALENESS_RULE_ENABLED, value=False))
    await session.commit()
    anime_id = anime.id  # captured before expire_all() below

    scanner._job_queue.enqueue = lambda job_type, factory: None
    count = await scanner.enqueue_metadata_rescan(ignore_staleness=False)

    assert count == 1
    session.expire_all()
    reloaded = await AnimeRepo(session).get(anime_id)
    assert reloaded.no_scan is True  # the scanner itself never clears it


@pytest.mark.asyncio
async def test_full_scan_consolidates_loose_files_in_download_folder(scanner_env, tmp_path) -> None:
    """Real-world download folders routinely have individual episode files
    with no per-anime subfolder at all -- these must be grouped by parsed
    release title into a subfolder before the rest of the scan runs, or they
    never become an Anime row at all (the scanner only looks at
    subdirectories)."""
    scanner, session = scanner_env
    root = tmp_path / "downloads"
    root.mkdir()
    (root / "No_Waifu_No_Life_02_ENG.mkv").write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "download", "Downloads")
    await scanner.full_scan_folder(folder)

    expected_dir = root / "No Waifu No Life"
    assert (expected_dir / "No_Waifu_No_Life_02_ENG.mkv").exists()
    assert not (root / "No_Waifu_No_Life_02_ENG.mkv").exists()

    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    animes = result.scalars().all()
    assert len(animes) == 1
    assert animes[0].directory_path == str(expected_dir)


@pytest.mark.asyncio
async def test_full_scan_does_not_consolidate_loose_files_in_content_folder(scanner_env, tmp_path) -> None:
    """Content folders are assumed already organized -- a loose file there is
    left exactly as-is (pre-existing behavior, unchanged): no anime row gets
    created for it since the scanner only walks subdirectories, but it must
    not get moved around either."""
    scanner, session = scanner_env
    root = tmp_path / "content"
    root.mkdir()
    loose = root / "No_Waifu_No_Life_02_ENG.mkv"
    loose.write_bytes(b"x" * 10)

    folder = await FolderRepo(session).create(str(root), "content", "Content")
    await scanner.full_scan_folder(folder)

    assert loose.exists()
    result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_full_scan_consolidation_leaves_file_in_place_on_name_collision(scanner_env, tmp_path) -> None:
    scanner, session = scanner_env
    root = tmp_path / "downloads"
    root.mkdir()
    target_dir = root / "No Waifu No Life"
    target_dir.mkdir()
    (target_dir / "No_Waifu_No_Life_02_ENG.mkv").write_bytes(b"already here")
    loose = root / "No_Waifu_No_Life_02_ENG.mkv"
    loose.write_bytes(b"new download")

    folder = await FolderRepo(session).create(str(root), "download", "Downloads")
    await scanner.full_scan_folder(folder)

    assert loose.exists()  # never overwritten, never deleted
    assert loose.read_bytes() == b"new download"
    assert (target_dir / "No_Waifu_No_Life_02_ENG.mkv").read_bytes() == b"already here"


@pytest.mark.asyncio
async def test_kept_empty_dir_is_not_offered_again(scanner_env, tmp_path) -> None:
    """An empty directory gets no Anime row, so without remembering the
    decision the delete prompt came back on every single scan."""
    from app.services.settings_store import remember_kept_empty_dir

    scanner, session = scanner_env
    root = tmp_path / "content"
    empty_dir = root / "Empty Show"
    empty_dir.mkdir(parents=True)
    folder = await FolderRepo(session).create(str(root), "content", "Content")

    events: list[dict] = []

    async def collect(payload: dict) -> None:
        events.append(payload)

    scanner._event_bus.subscribe(collect)

    await scanner.full_scan_folder(folder)
    assert [e["event"] for e in events] == ["folder.empty_dir_found"]

    await remember_kept_empty_dir(session, str(empty_dir))
    events.clear()

    await scanner.full_scan_folder(folder)
    assert events == []


@pytest.mark.asyncio
async def test_consolidation_survives_an_unmovable_loose_file(scanner_env, tmp_path, monkeypatch) -> None:
    """It runs before everything else in a download-folder scan -- one file
    in use must not cost the whole folder."""
    scanner, session = scanner_env
    root = tmp_path / "downloads"
    root.mkdir()
    (root / "Locked_01.mkv").write_bytes(b"x" * 10)
    (root / "Fine_01.mkv").write_bytes(b"x" * 10)
    folder = await FolderRepo(session).create(str(root), "download", "Downloads")

    real_rename = Path.rename

    def flaky_rename(self, target):
        if self.name.startswith("Locked"):
            raise PermissionError("file is open in another program")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    await scanner.full_scan_folder(folder)

    monkeypatch.undo()
    assert (root / "Locked_01.mkv").exists()  # left for the next scan
    assert (root / "Fine" / "Fine_01.mkv").exists()
    animes = (await session.execute(select(Anime).where(Anime.folder_id == folder.id))).scalars().all()
    assert [a.directory_path for a in animes] == [str(root / "Fine")]
