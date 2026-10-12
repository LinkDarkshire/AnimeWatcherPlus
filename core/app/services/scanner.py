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
from app.db.completeness import CompletenessRepo
from app.db.models import Folder
from app.db.repositories import AnimeRepo, FolderRepo, LocalEpisodeRepo
from app.db.session import session_scope
from app.providers.base import ProviderRegistry
from app.services import identification
from app.services.episode_parse import guess_episode_number, parse_release_filename
from app.services.jobs import EventBus, JobQueue
from app.services.media_files import (
    VIDEO_EXTENSIONS,
    has_user_files,
    has_video_files,
    is_ignored,
    is_video_file,
)
from app.services.settings_store import get_kept_empty_dirs, get_staleness_config
from app.services.sorter import sanitize_filename_component
from app.services.staleness import is_stale

logger = structlog.get_logger(__name__)


def _list_video_files(anime_dir: Path) -> list[tuple[str, str, int, float]]:
    """(path, filename, size, mtime) for every video file under the directory.
    Runs in a worker thread: on a network share this walk is the slow part of
    a scan, and it must not stall the API while it runs. A file that vanishes
    between listing and stat() is simply skipped."""
    files: list[tuple[str, str, int, float]] = []
    for f in anime_dir.rglob("*"):
        if not is_video_file(f):
            continue
        try:
            if not f.is_file():
                continue
            stat = f.stat()
        except OSError:
            continue
        files.append((str(f), f.name, stat.st_size, stat.st_mtime))
    return files


def _list_subdirs(root: Path) -> set[Path]:
    return {p for p in root.iterdir() if p.is_dir()}


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
    def __init__(self, scanner: ScannerService, folder: Folder) -> None:
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
    """Scans every folder at startup and then watches them for changes.

    A change isn't processed right away: files that are still being copied
    or downloaded would be read half-finished. Instead, one task per changing
    anime directory samples its (total size, newest mtime) every
    `scan_debounce_interval_s` and only goes ahead once that has stayed the
    same for `scan_debounce_checks` samples in a row.
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
        """Starts watching right away so no change is missed, then queues the
        full scan as a background job -- on a large library it can take a
        while, and the UI should be usable immediately."""
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
        task = asyncio.create_task(self._stabilize_and_process(folder, anime_dir))
        self._pending_checks[key] = task
        task.add_done_callback(partial(self._forget_check, key))

    def _forget_check(self, key: str, task: asyncio.Task) -> None:
        """Drops a finished check -- unless a newer one already replaced it."""
        if self._pending_checks.get(key) is task:
            del self._pending_checks[key]

    async def _stabilize_and_process(self, folder: Folder, anime_dir: Path) -> None:
        try:
            last_sig: tuple[int, float] | None = None
            stable_count = 0
            while stable_count < self._settings.scan_debounce_checks:
                await asyncio.sleep(self._settings.scan_debounce_interval_s)
                if not await asyncio.to_thread(anime_dir.exists):
                    await self._handle_removed(anime_dir)
                    return
                sig = await asyncio.to_thread(_directory_signature, anime_dir)
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
        online = await asyncio.to_thread(root.exists)
        await self._set_folder_offline(folder.id, not online)
        if not online:
            logger.warning("folder_offline", folder_id=folder.id, path=folder.path)
            return
        # A folder that was unreachable at startup (NAS still booting, VPN
        # down) never got a watcher; attach it now that it's back.
        if folder.active:
            self.watch_folder(folder)

        if folder.type == "download":
            await asyncio.to_thread(_consolidate_loose_files, root)

        current_dirs = await asyncio.to_thread(_list_subdirs, root)
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
                anime_path = Path(anime.directory_path)
                # Re-checked on disk, not just against the listing from the
                # start of the scan: a rename/sort through the API while this
                # (possibly long) scan ran moves the anime to a path that
                # listing never saw, and deleting it for that would be wrong.
                if anime_path not in current_dirs and not await asyncio.to_thread(anime_path.is_dir):
                    # The directory is gone, so its catalog entry goes too
                    # (episodes, tags and the rest along with it).
                    anime_id, path = anime.id, anime.directory_path
                    await anime_repo.delete(anime_id)
                    await self._event_bus.publish("anime.removed", {"anime_id": anime_id, "path": path})

    async def _set_folder_offline(self, folder_id: int, offline: bool) -> None:
        async with session_scope() as session:
            db_folder = await FolderRepo(session).get(folder_id)
            if db_folder is not None and db_folder.offline != offline:
                db_folder.offline = offline
                await session.commit()

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
                # The folder was removed from the app while this scan was
                # queued or running -- stop rather than write rows for it.
                logger.info("scan_aborted_folder_gone", folder_id=folder.id, path=str(anime_dir))
                return

            anime = await anime_repo.get_by_directory(str(anime_dir))
            is_new = anime is None
            if anime is None:
                if not await asyncio.to_thread(has_video_files, anime_dir):
                    # Don't catalog a directory with no episodes in it. Only a
                    # *truly* empty one is offered for deletion, though: no
                    # video files can just as well mean a download still in
                    # progress (.part files) or a folder of subtitles/archives,
                    # which must never end up behind a "delete" button.
                    # "Keep" is remembered, or the prompt would come back on
                    # every single scan for a directory the user already
                    # decided about.
                    if await asyncio.to_thread(has_user_files, anime_dir):
                        logger.debug("dir_without_videos_skipped", path=str(anime_dir))
                    elif str(anime_dir) not in await get_kept_empty_dirs(session):
                        await self._event_bus.publish(
                            "folder.empty_dir_found", {"folder_id": folder.id, "path": str(anime_dir)}
                        )
                    return
                anime = await anime_repo.create_pending(folder.id, str(anime_dir), anime_dir.name)
                await self._event_bus.publish(
                    "anime.discovered", {"anime_id": anime.id, "path": str(anime_dir)}
                )

            # Compare against what's already stored first: an unchanged file
            # costs one stat() and no DB write, which keeps rescans fast.
            existing_by_path = {ep.file_path: ep for ep in await episode_repo.by_anime(anime.id)}
            seen_paths: set[str] = set()
            episodes_changed = False
            for path_str, file_name, file_size, file_mtime in await asyncio.to_thread(
                _list_video_files, anime_dir
            ):
                seen_paths.add(path_str)
                existing = existing_by_path.get(path_str)
                parsed_number = guess_episode_number(file_name)
                if (
                    existing is not None
                    and existing.file_size == file_size
                    and existing.file_mtime == file_mtime
                    # Size and mtime only prove the file is unchanged, not that
                    # its stored episode number is still what the parser says
                    # today -- so the number is compared too (cheap, it's just
                    # string parsing). Hand-corrected numbers are kept.
                    and (existing.manual_override or existing.ep_number == parsed_number)
                ):
                    continue
                await episode_repo.upsert(
                    anime.id,
                    path_str,
                    file_size,
                    file_mtime,
                    parsed_number,
                )
                episodes_changed = True
            for path_str in existing_by_path:
                if path_str not in seen_paths:
                    await episode_repo.delete_by_path(path_str)
                    episodes_changed = True
            if await CompletenessRepo(session).assign_lone_file(anime.id):
                episodes_changed = True

            should_identify = is_new or anime.ident_status == "pending"

        if episodes_changed:
            # Files came, went or got a number: missing episodes, unassigned
            # files and the rename queue may all look different now.
            await self._event_bus.publish("anime.episodes_changed", {"anime_id": anime.id})

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

    async def enqueue_pending_identifications(self) -> int:
        """Puts every anime still waiting for identification back in the
        queue -- after an AniDB ban/limit ended, those jobs had all failed
        and nothing else would retry them before the next restart."""
        from sqlalchemy import select

        from app.db.models import Anime

        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Anime.id, Anime.directory_path).where(Anime.ident_status == "pending")
                )
            ).all()
        for anime_id, directory in rows:
            self._job_queue.enqueue("identify", partial(self._run_identify_if_pending, anime_id, Path(directory)))
        return len(rows)

    async def _run_identify_if_pending(self, anime_id: int, anime_dir: Path) -> None:
        # Re-checked when the job runs: a scan may have queued the same
        # anime meanwhile, and a second identification would be wasted.
        async with session_scope() as session:
            anime = await AnimeRepo(session).get(anime_id)
            if anime is None or anime.ident_status != "pending":
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
