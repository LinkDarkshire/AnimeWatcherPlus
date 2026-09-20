from __future__ import annotations

import asyncio
import os
from functools import partial
from pathlib import Path

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from app.config import Settings
from app.db.models import Folder
from app.db.repositories import AnimeRepo, FolderRepo, LocalEpisodeRepo
from app.db.session import session_scope
from app.providers.base import ProviderRegistry
from app.services import identification, pending_actions
from app.services.episode_parse import guess_episode_number, parse_release_filename
from app.services.jobs import EventBus, JobQueue
from app.services.settings_store import get_kept_empty_dirs, get_staleness_config
from app.services.sorter import sanitize_filename_component
from app.services.staleness import is_stale

logger = structlog.get_logger(__name__)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".wmv", ".flv", ".mov"}
IGNORED_SUFFIXES = {".part", ".crdownload", ".!ut", ".tmp", ".downloading"}


def is_ignored(path: Path) -> bool:
    return path.suffix.lower() in IGNORED_SUFFIXES


def has_video_files(directory: Path) -> bool:
    return any(
        f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and not is_ignored(f)
        for f in directory.rglob("*")
    )


def _consolidate_loose_files(root: Path) -> None:
    """Download folders routinely receive individual episode files with no
    per-anime subfolder at all (a fansub release dropped straight into the
    download root) -- but every downstream step (identification, the sort
    queue) assumes one subdirectory per anime, same as a content folder. Group
    any such loose video file into a subfolder named after its parsed release
    title before the rest of the scan runs, so it gets picked up exactly like
    any other anime directory. A plain rename within the same folder is
    always a same-volume, effectively-atomic move.
    """
    for file in list(root.iterdir()):
        if not file.is_file() or file.suffix.lower() not in VIDEO_EXTENSIONS or is_ignored(file):
            continue
        parsed = parse_release_filename(file.name)
        target_dir = root / sanitize_filename_component(parsed.title or file.stem)
        target_dir.mkdir(exist_ok=True)
        dest = target_dir / file.name
        if dest.exists():
            logger.warning("loose_file_consolidation_collision", path=str(file), dest=str(dest))
            continue
        try:
            file.rename(dest)
        except OSError:
            # A file still being written, or open in another program: skip it
            # and pick it up next scan. This runs before anything else in
            # full_scan_folder, so raising here would cost the entire folder.
            logger.warning("loose_file_consolidation_failed", path=str(file))


def anime_dir_for(path: Path, folder_root: Path) -> Path | None:
    """Maps any changed path back to its top-level anime directory under the
    watched folder root (one anime = one immediate subdirectory).
    """
    try:
        rel = path.relative_to(folder_root)
    except ValueError:
        return None
    if not rel.parts:
        return None
    return folder_root / rel.parts[0]


def _directory_signature(anime_dir: Path) -> tuple[int, float]:
    total_size = 0
    max_mtime = 0.0
    for f in anime_dir.rglob("*"):
        if f.is_file():
            try:
                stat = f.stat()
            except OSError:
                continue
            total_size += stat.st_size
            max_mtime = max(max_mtime, stat.st_mtime)
    return total_size, max_mtime


class _Handler(FileSystemEventHandler):
    def __init__(self, scanner: "ScannerService", folder: Folder) -> None:
        self._scanner = scanner
        self._folder = folder

    def _dispatch(self, event: FileSystemEvent) -> None:
        path = Path(os.fsdecode(event.src_path))
        if is_ignored(path):
            return
        self._scanner.notify_fs_event(self._folder, path)

    def on_created(self, event: FileSystemEvent) -> None:
        self._dispatch(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._dispatch(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._dispatch(event)
        self._scanner.notify_fs_event(self._folder, Path(os.fsdecode(event.dest_path)))

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._dispatch(event)


class ScannerService:
    """Startup full-scan (FA-02) + watchdog live-watch with debounce (FA-03).

    One asyncio task per "currently changing" anime directory implements the
    debounce: it keeps sampling a (total_size, max_mtime) signature every
    `scan_debounce_interval_s` and only proceeds once the signature has stayed
    identical for `scan_debounce_checks` consecutive samples (Edge Case 1).
    """

    def __init__(
        self,
        settings: Settings,
        provider_registry: ProviderRegistry,
        event_bus: EventBus,
        job_queue: JobQueue,
    ) -> None:
        self._settings = settings
        self._provider_registry = provider_registry
        self._event_bus = event_bus
        self._job_queue = job_queue
        self._observers: dict[int, BaseObserver] = {}
        self._pending_checks: dict[str, asyncio.Task] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Attaches live-watch immediately so no changes are missed, then hands
        the (potentially slow, large-library) full scan off to the background
        job queue instead of blocking startup (NFA-01: UI must be usable in
        <3s; the scan runs asynchronously afterwards)."""
        self._loop = asyncio.get_running_loop()
        async with session_scope() as session:
            folders = await FolderRepo(session).list_all()
        for folder in folders:
            if folder.active:
                self.watch_folder(folder)
                self._job_queue.enqueue("scan", partial(self.full_scan_folder, folder))
        await self.enqueue_metadata_rescan(ignore_staleness=False)

    async def stop(self) -> None:
        for observer in self._observers.values():
            observer.stop()
        for observer in self._observers.values():
            observer.join(timeout=2)
        self._observers.clear()
        for task in self._pending_checks.values():
            task.cancel()

    def watch_folder(self, folder: Folder) -> None:
        root = Path(folder.path)
        if not root.exists():
            logger.warning("folder_offline_skip_watch", folder_id=folder.id, path=folder.path)
            return
        if folder.id in self._observers:
            return
        handler = _Handler(self, folder)
        observer = Observer()
        observer.schedule(handler, str(root), recursive=True)
        observer.start()
        self._observers[folder.id] = observer

    def unwatch_folder(self, folder_id: int) -> None:
        observer = self._observers.pop(folder_id, None)
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)

    def notify_fs_event(self, folder: Folder, path: Path) -> None:
        """Called from the watchdog thread; bridges back onto the asyncio loop."""
        anime_dir = anime_dir_for(path, Path(folder.path))
        if anime_dir is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._debounce(folder, anime_dir), self._loop)

    async def _debounce(self, folder: Folder, anime_dir: Path) -> None:
        key = str(anime_dir)
        existing = self._pending_checks.get(key)
        if existing is not None and not existing.done():
            existing.cancel()
        self._pending_checks[key] = asyncio.create_task(self._stabilize_and_process(folder, anime_dir))

    async def _stabilize_and_process(self, folder: Folder, anime_dir: Path) -> None:
        try:
            last_sig: tuple[int, float] | None = None
            stable_count = 0
            while stable_count < self._settings.scan_debounce_checks:
                await asyncio.sleep(self._settings.scan_debounce_interval_s)
                if not anime_dir.exists():
                    await self._handle_removed(anime_dir)
                    return
                sig = _directory_signature(anime_dir)
                if sig == last_sig and sig != (0, 0.0):
                    stable_count += 1
                else:
                    stable_count = 0
                    last_sig = sig
            await self._process_anime_dir(folder, anime_dir)
        except asyncio.CancelledError:
            pass

    async def full_scan_folder(self, folder: Folder) -> None:
        root = Path(folder.path)
        if not root.exists():
            async with session_scope() as session:
                folder_repo = FolderRepo(session)
                db_folder = await folder_repo.get(folder.id)
                if db_folder is not None:
                    db_folder.offline = True
                    await session.commit()
            logger.warning("folder_offline", folder_id=folder.id, path=folder.path)
            return

        if folder.type == "download":
            _consolidate_loose_files(root)

        current_dirs = {p for p in root.iterdir() if p.is_dir()}
        for anime_dir in current_dirs:
            async with session_scope() as session:
                still_exists = await FolderRepo(session).get(folder.id) is not None
            if not still_exists:
                # Deleted concurrently while this (potentially long, e.g.
                # over a network share) background scan was running -- stop
                # instead of doing further pointless work.
                logger.info("scan_aborted_folder_gone", folder_id=folder.id)
                return
            await self._process_anime_dir(folder, anime_dir)
            if self._settings.scan_yield_interval_s > 0:
                await asyncio.sleep(self._settings.scan_yield_interval_s)

        async with session_scope() as session:
            anime_repo = AnimeRepo(session)
            from sqlalchemy import select

            from app.db.models import Anime

            result = await session.execute(select(Anime).where(Anime.folder_id == folder.id))
            for anime in result.scalars().all():
                if Path(anime.directory_path) not in current_dirs:
                    # No more soft "missing" state -- a previously-tracked
                    # folder that's gone is removed from the catalog
                    # outright, no confirmation (per user request). The
                    # existing FK-safe delete (built for the duplicate-
                    # resolution "delete one entry" flow) already handles
                    # cascading child rows correctly.
                    anime_id, path = anime.id, anime.directory_path
                    await anime_repo.delete(anime_id)
                    await self._event_bus.publish("anime.removed", {"anime_id": anime_id, "path": path})

    async def _handle_removed(self, anime_dir: Path) -> None:
        async with session_scope() as session:
            anime_repo = AnimeRepo(session)
            anime = await anime_repo.get_by_directory(str(anime_dir))
            if anime is not None:
                anime_id = anime.id  # captured before delete() -- see AnimeRepo.delete's own
                # note on session.rollback()/commit expiring attributes; anime.id after the
                # delete could trigger a lazy reload outside a valid greenlet context.
                await anime_repo.delete(anime_id)
                await self._event_bus.publish(
                    "anime.removed", {"anime_id": anime_id, "path": str(anime_dir)}
                )

    async def _process_anime_dir(self, folder: Folder, anime_dir: Path) -> None:
        async with session_scope() as session:
            folder_repo = FolderRepo(session)
            anime_repo = AnimeRepo(session)
            episode_repo = LocalEpisodeRepo(session)

            if await folder_repo.get(folder.id) is None:
                # The folder was deleted while this scan/debounce task was
                # already running or queued (e.g. a long scan over a network
                # share) -- stop instead of INSERTing against a folder_id
                # that no longer exists (FK violation).
                logger.info("scan_aborted_folder_gone", folder_id=folder.id, path=str(anime_dir))
                return

            anime = await anime_repo.get_by_directory(str(anime_dir))
            is_new = anime is None
            if anime is None:
                if not has_video_files(anime_dir):
                    # Don't catalog a directory with no episodes in it --
                    # surface it for the user to confirm deleting instead
                    # (it never got an Anime row, so there's nothing here to
                    # clean up on our end beyond publishing the event).
                    # "Keep" is remembered, or the prompt would come back on
                    # every single scan for a directory the user already
                    # decided about.
                    if str(anime_dir) not in await get_kept_empty_dirs(session):
                        await self._event_bus.publish(
                            "folder.empty_dir_found", {"folder_id": folder.id, "path": str(anime_dir)}
                        )
                    return
                anime = await anime_repo.create_pending(folder.id, str(anime_dir), anime_dir.name)
                await self._event_bus.publish(
                    "anime.discovered", {"anime_id": anime.id, "path": str(anime_dir)}
                )

            # Scan-Cache (NFA-03): compare against what's already known before
            # touching the DB, so an unchanged file costs a stat() call and
            # nothing else -- this is what keeps repeat/background scans fast.
            existing_by_path = {ep.file_path: ep for ep in await episode_repo.by_anime(anime.id)}
            seen_paths: set[str] = set()
            episodes_changed = False
            for video_file in anime_dir.rglob("*"):
                if not video_file.is_file() or video_file.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                if is_ignored(video_file):
                    continue
                stat = video_file.stat()
                path_str = str(video_file)
                seen_paths.add(path_str)
                existing = existing_by_path.get(path_str)
                parsed_number = guess_episode_number(video_file.name)
                if (
                    existing is not None
                    and existing.file_size == stat.st_size
                    and existing.file_mtime == stat.st_mtime
                    # The size/mtime cache only proves the *file* is unchanged,
                    # not that the number stored for it is still what the parser
                    # would say: numbers parsed by an older, weaker parser would
                    # otherwise stick forever (675 files in a real library came
                    # back as "missing episodes" that way). Re-parsing is pure
                    # string work, so this adds no I/O; a hand-corrected number
                    # is never touched.
                    and (existing.manual_override or existing.ep_number == parsed_number)
                ):
                    continue
                await episode_repo.upsert(
                    anime.id,
                    path_str,
                    stat.st_size,
                    stat.st_mtime,
                    parsed_number,
                )
                episodes_changed = True
            for path_str in existing_by_path:
                if path_str not in seen_paths:
                    await episode_repo.delete_by_path(path_str)
                    episodes_changed = True

            should_identify = is_new or anime.ident_status == "pending"

        if episodes_changed:
            # A new or removed episode file can add/clear a rename-queue entry
            # for an anime that already exists, and unlike discovery or
            # identification that publishes no event -- so the cached badge
            # total has to be dropped here directly.
            pending_actions.invalidate()

        if should_identify:
            self._job_queue.enqueue(
                "identify", lambda: self._run_identify(anime.id, anime_dir)
            )

    async def _run_identify(self, anime_id: int, anime_dir: Path) -> None:
        async with session_scope() as session:
            anime_repo = AnimeRepo(session)
            anime = await anime_repo.get(anime_id)
            if anime is None:
                return
            await identification.identify_anime(
                session, self._settings, anime, anime_dir, self._provider_registry, self._event_bus
            )

    async def enqueue_metadata_rescan(self, *, ignore_staleness: bool) -> int:
        """Re-checks AniDB for already-identified anime (new episodes, changed
        metadata). Run automatically on startup for everything the staleness
        rule doesn't exclude, or manually (with `ignore_staleness=True`) for a
        full-library refresh that bypasses the rule entirely.

        Anime already persisted as `no_scan` are skipped outright -- no
        is_stale() recomputation, no AniDB call -- instead of every startup
        re-deriving staleness for the whole library from scratch (which,
        for a large library, means hundreds of rate-limited AniDB calls
        queued up before anything else the user does can run). Newly-stale
        anime get flagged here so the *next* startup skips them too.

        `ignore_staleness=True` (Force Full Scan) still re-checks *every*
        identified anime against AniDB regardless of `no_scan` -- but does
        NOT clear the flag itself. Only an explicit AniDB-ID change
        (identification.py, e.g. resolving a misidentified duplicate) may
        ever un-flag an anime; a same-ID refresh finding fresher data must
        not silently pull it back into the automatic rotation on its own.

        One job per anime, all funneled through the same serial job queue the
        rest of the app uses -- that's also what keeps this within the AniDB
        rate limiter's pace without any extra throttling here.
        """
        async with session_scope() as session:
            threshold_days, rule_enabled = await get_staleness_config(session)
            anime_repo = AnimeRepo(session)
            animes = await anime_repo.list_identified()
            skip_rule = ignore_staleness or not rule_enabled

            if skip_rule:
                to_rescan = animes
            else:
                to_rescan = []
                newly_no_scan = []
                for a in animes:
                    if a.no_scan:
                        continue
                    if is_stale(a, threshold_days):
                        newly_no_scan.append(a.id)
                    else:
                        to_rescan.append(a)
                await anime_repo.mark_no_scan(newly_no_scan)

            due = [(a.id, Path(a.directory_path)) for a in to_rescan]

        for anime_id, anime_dir in due:
            self._job_queue.enqueue("rescan", partial(self._run_rescan, anime_id, anime_dir))
        logger.info(
            "metadata_rescan_enqueued", count=len(due), total_identified=len(animes), ignore_staleness=ignore_staleness
        )
        return len(due)

    async def _run_rescan(self, anime_id: int, anime_dir: Path) -> None:
        async with session_scope() as session:
            anime_repo = AnimeRepo(session)
            anime = await anime_repo.get(anime_id)
            if anime is None or anime.anidb_id is None:
                return
            await identification.manual_identify(
                session,
                self._settings,
                anime,
                anime_dir,
                anime.anidb_id,
                self._provider_registry,
                self._event_bus,
            )
