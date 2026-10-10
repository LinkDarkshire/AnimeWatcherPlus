from __future__ import annotations

import errno
import os
import re
import shutil
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Anime, ExpectedEpisode, Folder, LocalEpisode
from app.db.repositories import AnimeRepo, FolderRepo, LocalEpisodeRepo
from app.services import artwork, nfo
from app.services.jobs import EventBus
from app.services.media_files import companion_files, has_video_files, remove_dir_if_empty
from app.services.settings_store import get_folder_title_order, get_rename_mode, get_sort_mode
from app.services.titles import has_known_variants, title_for

logger = structlog.get_logger(__name__)

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


class SortConflict(Exception):
    """Raised when sort_anime can't proceed: nothing matched at all, or (in
    the relocate case, where a new anime directory would be created) only a
    partial match -- moving just the matched subset there would leave the
    rest orphaned in the old directory with no anime row tracking them."""


@dataclass
class SortResult:
    moved: int
    unmatched: int
    target_anime_id: int


@dataclass
class SortQueueEntry:
    anime_id: int
    title: str
    directory_path: str
    anidb_id: int
    episode_count: int
    matched_count: int
    suggested_target_folder_id: int | None


class EpisodeFile(Protocol):
    """A local episode as the matcher sees it. Satisfied by the LocalEpisode
    model and by the flat `(anime_id, file_path, ep_number)` rows the queue
    listings select instead of loading entities."""

    @property
    def file_path(self) -> str: ...
    @property
    def ep_number(self) -> str | None: ...


class ExpectedEpisodeInfo(Protocol):
    """The provider-side counterpart: number plus optional episode name."""

    @property
    def ep_number(self) -> str: ...
    @property
    def title(self) -> str | None: ...


class RenameQueueRow(Protocol):
    """The anime columns the rename queue selects."""

    @property
    def id(self) -> int: ...
    @property
    def title(self) -> str: ...
    @property
    def directory_path(self) -> str: ...
    @property
    def title_main(self) -> str | None: ...
    @property
    def title_en(self) -> str | None: ...
    @property
    def title_ja(self) -> str | None: ...


def sanitize_filename_component(name: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", name)
    return cleaned.strip(" .") or "Unknown"


def _normalize_ep_number(value: str | None) -> str | None:
    """Local guesses (episode_parse.guess_episode_number) and AniDB's normal-
    episode numbering are both plain digit strings, just not always zero-
    padded the same way -- normalize both sides so "05" and "5" match. AniDB
    specials/credits/trailers use letter-prefixed numbering (S1, C1, ...)
    that guess_episode_number never produces, so they naturally never match
    here and are left for manual handling instead of a wrong auto-match."""
    if value is None or not value.isdigit():
        return None
    return str(int(value))


def match_local_episodes(
    local_episodes: Sequence[EpisodeFile], expected_episodes: Sequence[ExpectedEpisodeInfo]
) -> list[tuple[EpisodeFile, ExpectedEpisodeInfo | None]]:
    expected_by_number: dict[str, ExpectedEpisodeInfo] = {}
    for expected in expected_episodes:
        norm = _normalize_ep_number(expected.ep_number)
        if norm is not None:
            expected_by_number[norm] = expected

    matches: list[tuple[EpisodeFile, ExpectedEpisodeInfo | None]] = []
    for local in local_episodes:
        norm = _normalize_ep_number(local.ep_number)
        matches.append((local, expected_by_number.get(norm) if norm is not None else None))
    return matches


def build_episode_filename(anime_title: str, ep_number: str, ep_title: str | None, suffix: str) -> str:
    """"{Title} - S01E{episode} - {Episode name}" -- season is always 01:
    match_local_episodes only ever matches plain-numbered (non-special)
    episodes, so there's no season ambiguity to resolve here."""
    return _episode_filename(sanitize_filename_component(anime_title), ep_number, ep_title, suffix)


def _episode_filename(sanitized_title: str, ep_number: str, ep_title: str | None, suffix: str) -> str:
    """Same as `build_episode_filename`, but for callers that already
    sanitized the title -- the queue pass builds one filename per episode in
    the library and would otherwise re-run the sanitizing regex over the same
    title for every one of them.

    The episode-name segment is always present: the scheme is fixed at
    "{Title} - S01E{episode} - {episode name}", so an episode the provider
    lists without a name gets the same generic "Episode N" the episode NFO
    uses, rather than a filename in a different shape from its neighbours."""
    number = int(ep_number)
    name = ep_title or f"Episode {number}"
    return f"{sanitized_title} - S01E{number:02d} - {sanitize_filename_component(name)}{suffix}"


def _is_same_file(a: Path, b: Path) -> bool:
    """Whether two paths name the same file on disk. `exists()` can't answer
    this on a case-insensitive filesystem: renaming "show - s01e01.mkv" to
    "Show - S01E01.mkv" reports the target as already existing, when it is
    the very file being renamed."""
    try:
        return a.samefile(b)
    except OSError:
        return False


def _dedupe_path(src: Path, dest: Path) -> Path:
    if not dest.exists() or _is_same_file(src, dest):
        return dest
    counter = 2
    while True:
        candidate = dest.with_name(f"{dest.stem} ({counter}){dest.suffix}")
        # The source itself may already hold one of the numbered names (it is
        # the second copy of an episode): that slot is free for it, or every
        # rename would bump it from " (2)" to " (3)" and back.
        if not candidate.exists() or _is_same_file(src, candidate):
            return candidate
        counter += 1


def move_file(src: Path, dest: Path) -> Path:
    """NFA-09: loss-safe move. Same-volume is an atomic rename; a cross-
    device destination can't rename() so it falls back to copy + size-verify
    + only-then-delete-source, so an interrupted or failed copy never costs
    the original file. Never overwrites a *different* existing file at dest --
    a real collision gets a " (2)", " (3)", ... suffix instead, while a
    case-only rename of the file itself goes through as the rename it is.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = _dedupe_path(src, dest)
    try:
        src.rename(dest)
        return dest
    except OSError as exc:
        # Only a cross-device move may fall back to copying. Anything else --
        # a locked file, a permission problem, a vanished source -- must
        # surface: copying those would succeed and then fail to delete the
        # source, silently leaving the episode on disk twice.
        if exc.errno != errno.EXDEV:
            raise

    shutil.copy2(src, dest)
    if dest.stat().st_size != src.stat().st_size:
        dest.unlink(missing_ok=True)
        raise OSError(f"copy verification failed for {src} -> {dest}") from None
    try:
        src.unlink()
    except OSError:
        # The copy is verified but the original can't go. Drop the copy so
        # the move is all-or-nothing rather than leaving a duplicate behind.
        dest.unlink(missing_ok=True)
        raise
    return dest


def move_episode_file(src: Path, dest: Path) -> Path:
    """Moves an episode file together with every file named after it: the
    per-episode NFO written next to it (FA-09), external subtitles
    (`.ass`, `.en.srt`), separate audio tracks (`.mka`) and the like. Without
    this a rename strands `Old Name.nfo`/`Old Name.ass` beside
    `New Name.mkv` -- Jellyfin/Kodi read the NFO as a separate episode and
    players stop loading the subtitles."""
    companions = companion_files(src)
    moved = move_file(src, dest)
    for companion in companions:
        # Keep everything after the episode's own stem: ".en.srt" stays ".en.srt".
        target = moved.with_name(moved.stem + companion.name[len(src.stem):])
        try:
            move_file(companion, target)
        except OSError:
            # A companion that can't follow must never fail the episode move.
            logger.warning("episode_companion_move_failed", path=str(companion))
    return moved


async def _find_target_anime(session: AsyncSession, target_folder_id: int, anidb_id: int) -> Anime | None:
    result = await session.execute(
        select(Anime).where(Anime.anidb_id == anidb_id, Anime.folder_id == target_folder_id)
    )
    return result.scalar_one_or_none()


async def _suggest_target_folder(session: AsyncSession, anidb_id: int) -> int | None:
    result = await session.execute(
        select(Anime.folder_id)
        .join(Folder, Folder.id == Anime.folder_id)
        .where(Anime.anidb_id == anidb_id, Folder.type == "content")
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None


def _remove_sidecars(anime_dir: Path) -> None:
    for filename in (artwork.POSTER_FILENAME, nfo.TVSHOW_NFO, artwork.ANIINFO_FILENAME):
        (anime_dir / filename).unlink(missing_ok=True)


def _move_remaining_files(source_dir: Path, new_dir: Path) -> None:
    """Relocation moves the whole anime, so whatever is left in the source
    once the episodes are out -- fonts, extras, subtitles not named after one
    episode -- goes along, keeping its relative path. Best-effort: anything
    that can't be moved is left where it is (and keeps the source directory
    from being removed) rather than lost."""
    for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
        try:
            move_file(path, new_dir / path.relative_to(source_dir))
        except OSError:
            logger.warning("leftover_file_move_failed", path=str(path))


def _cleanup_source_dir(source_dir: Path) -> None:
    """Removes the emptied source directory -- but only if it really is
    empty. It used to be rmtree'd as soon as no *video* was left in it, which
    deleted subtitles and other files that were never moved anywhere."""
    try:
        if not remove_dir_if_empty(source_dir):
            logger.warning("source_dir_kept_not_empty", path=str(source_dir))
    except OSError:
        logger.warning("source_dir_cleanup_failed", path=str(source_dir))


async def sort_anime(
    session: AsyncSession, event_bus: EventBus, source_anime_id: int, target_folder_id: int
) -> SortResult:
    """Moves+renames every episode file of a download-folder anime that can
    be matched to an expected episode into the target content folder --
    merging into an already-existing anime there if one shares the AniDB ID
    (e.g. weekly episodes for an ongoing show), or relocating the whole
    anime there otherwise. Caller (the API layer) is responsible for 404/400
    validation of the anime/folder themselves; this only raises SortConflict
    for the two 409-worthy cases described on that exception.
    """
    anime_repo = AnimeRepo(session)
    episode_repo = LocalEpisodeRepo(session)

    anime = await anime_repo.get(source_anime_id)
    if anime is None or anime.anidb_id is None:
        raise SortConflict("Anime ist nicht identifiziert")

    local_episodes = await episode_repo.by_anime(anime.id)
    if not local_episodes:
        raise SortConflict("Keine lokalen Episoden-Dateien vorhanden")

    matches = match_local_episodes(local_episodes, anime.expected_episodes)
    matched = [(local, expected) for local, expected in matches if expected is not None]
    unmatched_count = len(matches) - len(matched)
    if not matched:
        raise SortConflict("Keine Episode konnte einer erwarteten Episode zugeordnet werden")

    source_dir = Path(anime.directory_path)
    target_anime = await _find_target_anime(session, target_folder_id, anime.anidb_id)
    folder_order = await get_folder_title_order(session)

    if target_anime is not None:
        target_dir = Path(target_anime.directory_path)
        target_title = title_for(target_anime, folder_order)
        for local_ep, expected in matched:
            src = Path(local_ep.file_path)
            try:
                dest = move_episode_file(
                    src,
                    target_dir
                    / build_episode_filename(target_title, expected.ep_number, expected.title, src.suffix),
                )
            except OSError as exc:
                # Every file moved so far is already recorded under the target
                # anime, so stopping here leaves the DB consistent; the rest
                # stays in the sort queue.
                raise SortConflict(f"Datei konnte nicht verschoben werden: {exc}") from exc
            await episode_repo.delete_by_path(str(src))
            stat = dest.stat()
            await episode_repo.upsert(
                target_anime.id, str(dest), stat.st_size, stat.st_mtime, _normalize_ep_number(expected.ep_number)
            )

        if not has_video_files(source_dir):
            # No episode left to track, so the catalog entry goes. The
            # directory itself only goes if nothing else is left in it.
            _remove_sidecars(source_dir)
            _cleanup_source_dir(source_dir)
            await anime_repo.delete(source_anime_id)
            await event_bus.publish("anime.removed", {"anime_id": source_anime_id, "path": str(source_dir)})

        await event_bus.publish(
            "anime.sorted", {"anime_id": target_anime.id, "moved": len(matched), "unmatched": unmatched_count}
        )
        return SortResult(moved=len(matched), unmatched=unmatched_count, target_anime_id=target_anime.id)

    if unmatched_count > 0:
        raise SortConflict(
            "Nicht alle Episoden konnten zugeordnet werden -- ein Umzug in einen neuen Ordner "
            "erfordert einen vollständigen Abgleich"
        )

    target_folder = await FolderRepo(session).get(target_folder_id)
    assert target_folder is not None  # validated by the API layer before calling in
    folder_title = title_for(anime, folder_order)
    new_dir = Path(target_folder.path) / sanitize_filename_component(folder_title)
    new_dir_existed = new_dir.exists()
    new_dir.mkdir(parents=True, exist_ok=True)

    # Move every file first and only then touch the DB: if one move fails
    # (a file open in a player), the ones already moved go back, so the anime
    # is never split across two directories with half its rows pointing at
    # each.
    moves: list[tuple[Path, Path, str | None]] = []
    try:
        for local_ep, expected in matched:
            src = Path(local_ep.file_path)
            dest = move_episode_file(
                src, new_dir / build_episode_filename(folder_title, expected.ep_number, expected.title, src.suffix)
            )
            moves.append((src, dest, _normalize_ep_number(expected.ep_number)))
    except OSError as exc:
        for src, dest, _ in reversed(moves):
            try:
                move_episode_file(dest, src)
            except OSError:
                logger.error("sort_rollback_failed", src=str(dest), dest=str(src))
        if not new_dir_existed:
            _cleanup_source_dir(new_dir)
        raise SortConflict(f"Datei konnte nicht verschoben werden: {exc}") from exc

    for src, dest, ep_number in moves:
        await episode_repo.delete_by_path(str(src))
        stat = dest.stat()
        await episode_repo.upsert(anime.id, str(dest), stat.st_size, stat.st_mtime, ep_number)

    _move_remaining_files(source_dir, new_dir)

    anime_row = await session.get(Anime, source_anime_id)
    assert anime_row is not None
    anime_row.folder_id = target_folder_id
    anime_row.directory_path = str(new_dir)
    await session.commit()

    _cleanup_source_dir(source_dir)

    await event_bus.publish("anime.sorted", {"anime_id": source_anime_id, "moved": len(matched), "unmatched": 0})
    return SortResult(moved=len(matched), unmatched=0, target_anime_id=source_anime_id)


# Queue listings are shown alphabetically; case-insensitive, so "attack on
# titan" doesn't sort after "Zombie".
_BY_TITLE = Anime.title.collate("NOCASE")

_SORT_QUEUE_PREDICATE = (
    Folder.type == "download",
    Anime.ident_status == "identified",
    Anime.anidb_id.is_not(None),
)


async def _rows_by_anime(session: AsyncSession, stmt: Any) -> dict[int, list[Any]]:
    """Groups a flat `(anime_id, ...)` column select by anime.

    The returned SQLAlchemy Rows expose the selected columns as attributes, so
    they drop straight into `match_local_episodes` / `_compute_rename_plan` in
    place of LocalEpisode/ExpectedEpisode ORM instances -- those only ever read
    `.ep_number`, `.file_path` and `.title`. Selecting columns instead of
    entities skips identity-map bookkeeping and per-row object construction,
    which is the bulk of the cost once a library has tens of thousands of
    episode rows.
    """
    grouped: dict[int, list[Any]] = defaultdict(list)
    for row in (await session.execute(stmt)).all():
        grouped[row.anime_id].append(row)
    return grouped


async def _suggested_target_folders(session: AsyncSession, anidb_ids: set[int]) -> dict[int, int]:
    """One query mapping AniDB ID -> content folder already holding that anime,
    replacing a per-entry `_suggest_target_folder` call (the sort queue's old
    N+1)."""
    if not anidb_ids:
        return {}
    result = await session.execute(
        select(Anime.anidb_id, Anime.folder_id)
        .join(Folder, Folder.id == Anime.folder_id)
        .where(Anime.anidb_id.in_(anidb_ids), Folder.type == "content")
    )
    suggestions: dict[int, int] = {}
    for anidb_id, folder_id in result.all():
        suggestions.setdefault(anidb_id, folder_id)
    return suggestions


async def list_sort_queue(session: AsyncSession) -> list[SortQueueEntry]:
    """Flat column selects instead of ORM objects with `selectinload`: this
    runs behind the nav badge's pending-actions count, so it must stay cheap
    on a large library."""
    rows = (
        await session.execute(
            select(Anime.id, Anime.title, Anime.directory_path, Anime.anidb_id)
            .join(Folder, Folder.id == Anime.folder_id)
            .where(*_SORT_QUEUE_PREDICATE)
            .order_by(_BY_TITLE)
        )
    ).all()
    if not rows:
        return []

    local_by_anime = await _rows_by_anime(
        session,
        select(LocalEpisode.anime_id, LocalEpisode.file_path, LocalEpisode.ep_number)
        .join(Anime, Anime.id == LocalEpisode.anime_id)
        .join(Folder, Folder.id == Anime.folder_id)
        .where(*_SORT_QUEUE_PREDICATE),
    )
    expected_by_anime = await _rows_by_anime(
        session,
        select(ExpectedEpisode.anime_id, ExpectedEpisode.ep_number, ExpectedEpisode.title)
        .join(Anime, Anime.id == ExpectedEpisode.anime_id)
        .join(Folder, Folder.id == Anime.folder_id)
        .where(*_SORT_QUEUE_PREDICATE),
    )
    suggestions = await _suggested_target_folders(
        session, {row.anidb_id for row in rows if row.id in local_by_anime}
    )

    entries: list[SortQueueEntry] = []
    for row in rows:
        local_episodes = local_by_anime.get(row.id)
        if not local_episodes:
            continue
        matches = match_local_episodes(local_episodes, expected_by_anime.get(row.id, []))
        entries.append(
            SortQueueEntry(
                anime_id=row.id,
                title=row.title,
                directory_path=row.directory_path,
                anidb_id=row.anidb_id,
                episode_count=len(local_episodes),
                matched_count=sum(1 for _, expected in matches if expected is not None),
                suggested_target_folder_id=suggestions.get(row.anidb_id),
            )
        )
    return entries


async def count_sort_queue(session: AsyncSession) -> int:
    """Pure-SQL equivalent of `len(await list_sort_queue(...))` -- the badge
    only needs the number, not the entries, and an EXISTS beats loading every
    download-folder anime's episodes to check the same thing."""
    has_episode = (
        select(LocalEpisode.id).where(LocalEpisode.anime_id == Anime.id).exists()
    )
    result = await session.execute(
        select(func.count())
        .select_from(Anime)
        .join(Folder, Folder.id == Anime.folder_id)
        .where(*_SORT_QUEUE_PREDICATE, has_episode)
    )
    return result.scalar_one()


async def _resolve_unambiguous_target(session: AsyncSession, anidb_id: int) -> int | None:
    existing = await _suggest_target_folder(session, anidb_id)
    if existing is not None:
        return existing
    content_folders = (
        (await session.execute(select(Folder.id).where(Folder.type == "content", Folder.active.is_(True))))
        .scalars()
        .all()
    )
    return content_folders[0] if len(content_folders) == 1 else None


async def maybe_auto_sort(session: AsyncSession, event_bus: EventBus, anime_id: int) -> None:
    """Called right after a successful identification. Only ever acts when
    the anime lives in a download folder and sort_mode is "auto" -- and even
    then, only when the target is unambiguous without a rule engine (an
    existing same-AniDB-ID anime in a content folder, or exactly one active
    content folder overall). Anything else is left for manual resolution via
    the sort queue, "auto" or not.
    """
    anime = await session.get(Anime, anime_id)
    if anime is None or anime.anidb_id is None:
        return
    folder = await session.get(Folder, anime.folder_id)
    if folder is None or folder.type != "download":
        return
    if await get_sort_mode(session) != "auto":
        return

    target_folder_id = await _resolve_unambiguous_target(session, anime.anidb_id)
    if target_folder_id is None:
        return

    try:
        await sort_anime(session, event_bus, anime_id, target_folder_id)
    except SortConflict:
        # Nothing matched yet, or an incomplete relocate-case match -- stays
        # in the sort queue for the user to resolve by hand.
        logger.info("auto_sort_deferred", anime_id=anime_id)


class RenameConflict(Exception):
    """Raised when rename_anime can't proceed: the target directory name is
    already taken by a different, unrelated directory -- refuses rather than
    merging arbitrary pre-existing content into it."""


@dataclass
class RenameResult:
    renamed_dir: bool
    renamed_files: int


@dataclass
class RenameQueueEntry:
    anime_id: int
    title: str
    current_dir_name: str
    target_dir_name: str
    mismatched_file_count: int
    total_matched_episodes: int


@dataclass
class _RenamePlan:
    dir_needs_rename: bool
    target_dir_name: str
    # (episode, new filename) -- a LocalEpisode when the plan came from
    # rename_anime (which mutates it), a flat column row when it came from the
    # queue listing (which only counts).
    file_renames: list[tuple[EpisodeFile, str]]
    matched_total: int


def _compute_rename_plan(
    directory_path: str,
    folder_title: str,
    local_episodes: Sequence[EpisodeFile],
    expected_episodes: Sequence[ExpectedEpisodeInfo],
) -> _RenamePlan:
    """Unlike sorting (which moves between folders), renaming stays in the
    same parent directory -- there's no target-folder ambiguity to resolve,
    just "does the current name already match the identified title?".
    Unmatched local episode files are left untouched here too, same policy
    as sort_anime.

    `folder_title` is resolved by the caller from the user's
    `folder_title_order`, which is deliberately independent of the display
    title in `anime.title`. The episode arguments are taken as plain sequences
    rather than ORM instances so the queue listing can feed it flat column
    rows (see `_rows_by_anime`).
    """
    current_dir = Path(directory_path)
    target_dir_name = sanitize_filename_component(folder_title)
    dir_needs_rename = current_dir.name != target_dir_name

    matched = [
        (local, expected)
        for local, expected in match_local_episodes(local_episodes, expected_episodes)
        if expected is not None
    ]
    file_renames: list[tuple[EpisodeFile, str]] = []

    # Two files can match the same episode (a 720p and a 1080p copy, v1 and
    # v2). Only one of them can have the canonical name; the other gets
    # " (2)" -- and that has to count as correctly named, or it would sit in
    # the rename queue forever. Names are reserved per directory and compared
    # case-insensitively, since that's how Windows sees a collision.
    # os.path instead of Path(): counting the queue runs this once per episode
    # in the entire library, and constructing pathlib objects per episode was
    # by far the most expensive thing that pass did.
    taken: set[tuple[str, str]] = set()
    unsettled: list[tuple[EpisodeFile, str, str, str]] = []
    for local, expected in matched:
        parent, current_name = os.path.split(local.file_path)
        target_name = _episode_filename(
            target_dir_name, expected.ep_number, expected.title, os.path.splitext(current_name)[1]
        )
        key = (parent, current_name.lower())
        if _is_name_variant(current_name, target_name) and key not in taken:
            taken.add(key)
        else:
            unsettled.append((local, parent, current_name, target_name))

    for local, parent, current_name, target_name in unsettled:
        name = _free_name_variant(parent, target_name, taken)
        taken.add((parent, name.lower()))
        if name != current_name:
            file_renames.append((local, name))

    return _RenamePlan(
        dir_needs_rename=dir_needs_rename,
        target_dir_name=target_dir_name,
        file_renames=file_renames,
        matched_total=len(matched),
    )


def _is_name_variant(name: str, target: str) -> bool:
    """`target` itself, or `target` with a " (n)" collision suffix."""
    if name == target:
        return True
    stem, suffix = os.path.splitext(target)
    return re.fullmatch(re.escape(stem) + r" \(\d+\)" + re.escape(suffix), name) is not None


def _free_name_variant(parent: str, target: str, taken: set[tuple[str, str]]) -> str:
    if (parent, target.lower()) not in taken:
        return target
    stem, suffix = os.path.splitext(target)
    counter = 2
    while (parent, f"{stem} ({counter}){suffix}".lower()) in taken:
        counter += 1
    return f"{stem} ({counter}){suffix}"


async def rename_anime(session: AsyncSession, event_bus: EventBus, anime_id: int) -> RenameResult:
    """Normalizes an already-identified anime's directory name and matched
    episode filenames to the canonical `{Title} - S01E{episode} - {episode
    title}` scheme -- independent of sorting, so it also fixes up anime that
    were never in a download folder at all (e.g. long-standing content-folder
    entries with names inherited from an older tool)."""
    anime_repo = AnimeRepo(session)
    episode_repo = LocalEpisodeRepo(session)

    anime = await anime_repo.get(anime_id)
    if anime is None or anime.anidb_id is None:
        return RenameResult(renamed_dir=False, renamed_files=0)
    if not has_known_variants(anime):
        # Without language-tagged variants the only name available is the
        # untagged legacy title, which for many older entries is Japanese
        # script -- renaming a correctly romanized folder to that is exactly
        # the damage this refuses to do.
        raise RenameConflict(
            "Titel-Varianten unbekannt – bitte zuerst die Metadaten aktualisieren"
        )

    local_episodes = await episode_repo.by_anime(anime.id)
    folder_order = await get_folder_title_order(session)
    plan = _compute_rename_plan(
        anime.directory_path,
        title_for(anime, folder_order),
        local_episodes,
        anime.expected_episodes,
    )
    if not plan.dir_needs_rename and not plan.file_renames:
        return RenameResult(renamed_dir=False, renamed_files=0)

    current_dir = Path(anime.directory_path)
    target_dir = current_dir
    if plan.dir_needs_rename:
        target_dir = current_dir.parent / plan.target_dir_name
        # `exists()` alone isn't a collision test on Windows (and macOS): the
        # filesystem is case-insensitive, so a pure casing fix -- "attack on
        # titan" -> "Attack on Titan" -- reports the target as already
        # existing even though it *is* the very directory being renamed. That
        # made such an anime permanently unrenamable: every resolve attempt
        # 409'd and it stayed in the rename queue forever. samefile() tells
        # the two cases apart by identity instead of by name.
        if target_dir.exists() and not target_dir.samefile(current_dir):
            raise RenameConflict(f"Zielverzeichnis '{plan.target_dir_name}' existiert bereits")
        try:
            current_dir.rename(target_dir)
        except OSError as exc:
            # Windows refuses to rename a directory while any file in it is
            # open (a player, an Explorer preview). Nothing has changed yet.
            raise RenameConflict(f"Verzeichnis konnte nicht umbenannt werden: {exc}") from exc
        anime.directory_path = str(target_dir)
        # The whole directory just moved atomically (same volume, always --
        # it's a rename within the same parent), so every file already
        # physically lives at its new path; only the DB's recorded paths
        # are stale now, for matched and unmatched episodes alike. Relative
        # to the directory, not just by filename: episodes can sit in
        # subfolders ("Season 1/..."), which must survive the rewrite.
        for local in local_episodes:
            local.file_path = str(target_dir / Path(local.file_path).relative_to(current_dir))
        await session.commit()

    renamed_files = 0
    failure: OSError | None = None
    for episode, target_filename in plan.file_renames:
        # Here the plan was built from real ORM rows, so the path write below
        # lands in the DB (the queue listing feeds the same planner read-only
        # column rows, which is why the plan itself is typed by protocol).
        local = cast(LocalEpisode, episode)
        src = Path(local.file_path)
        try:
            dest = move_episode_file(src, src.parent / target_filename)
        except OSError as exc:
            # A single locked file (open in a player, say) must not leave the
            # rest of the series half-renamed with stale paths in the DB.
            failure = exc
            break
        local.file_path = str(dest)
        renamed_files += 1
    if renamed_files:
        await session.commit()

    if renamed_files or plan.dir_needs_rename:
        await event_bus.publish(
            "anime.renamed",
            {"anime_id": anime.id, "renamed_dir": plan.dir_needs_rename, "renamed_files": renamed_files},
        )
    if failure is not None:
        raise RenameConflict(f"Datei konnte nicht umbenannt werden: {failure}") from failure
    return RenameResult(renamed_dir=plan.dir_needs_rename, renamed_files=renamed_files)


_RENAME_QUEUE_PREDICATE = (
    Anime.ident_status == "identified",
    Anime.anidb_id.is_not(None),
    # Only anime whose language-tagged title variants are known -- see
    # titles.has_known_variants. Filtered here in SQL so the unnamed rows are
    # never loaded, instead of being skipped one by one in Python.
    or_(Anime.title_main.is_not(None), Anime.title_en.is_not(None), Anime.title_ja.is_not(None)),
)



async def _iter_rename_queue(session: AsyncSession) -> list[tuple[RenameQueueRow, _RenamePlan]]:
    """Every identified anime that doesn't match the canonical naming scheme,
    as (anime row, plan) pairs.

    Whether an anime needs renaming can't be decided in SQL -- it depends on
    comparing each filename against a title resolved from a user setting -- so
    this is inherently a full pass over the library. What it avoids is doing
    that pass through the ORM: three flat column selects, no entity
    construction, no `selectinload` round trips, and no per-anime query.
    """
    rows = (
        await session.execute(
            select(
                Anime.id,
                Anime.title,
                Anime.directory_path,
                Anime.title_main,
                Anime.title_en,
                Anime.title_ja,
            )
            .where(*_RENAME_QUEUE_PREDICATE)
            .order_by(_BY_TITLE)
        )
    ).all()
    if not rows:
        return []

    local_by_anime = await _rows_by_anime(
        session,
        select(LocalEpisode.anime_id, LocalEpisode.file_path, LocalEpisode.ep_number)
        .join(Anime, Anime.id == LocalEpisode.anime_id)
        .where(*_RENAME_QUEUE_PREDICATE),
    )
    expected_by_anime = await _rows_by_anime(
        session,
        select(ExpectedEpisode.anime_id, ExpectedEpisode.ep_number, ExpectedEpisode.title)
        .join(Anime, Anime.id == ExpectedEpisode.anime_id)
        .where(*_RENAME_QUEUE_PREDICATE),
    )
    folder_order = await get_folder_title_order(session)

    pending: list[tuple[RenameQueueRow, _RenamePlan]] = []
    for row in rows:
        local_episodes = local_by_anime.get(row.id)
        if not local_episodes:
            continue
        plan = _compute_rename_plan(
            row.directory_path,
            title_for(row, folder_order),
            local_episodes,
            expected_by_anime.get(row.id, []),
        )
        if plan.dir_needs_rename or plan.file_renames:
            pending.append((row, plan))
    return pending


async def list_rename_queue(session: AsyncSession) -> list[RenameQueueEntry]:
    return [
        RenameQueueEntry(
            anime_id=row.id,
            title=row.title,
            current_dir_name=Path(row.directory_path).name,
            target_dir_name=plan.target_dir_name,
            mismatched_file_count=len(plan.file_renames),
            total_matched_episodes=plan.matched_total,
        )
        for row, plan in await _iter_rename_queue(session)
    ]


async def count_rename_queue(session: AsyncSession) -> int:
    return len(await _iter_rename_queue(session))


@dataclass
class RenameProposal:
    current_dir_name: str
    target_dir_name: str
    dir_needs_rename: bool
    file_renames: list[tuple[str, str]]  # (current filename, target filename)


async def rename_proposal_for(session: AsyncSession, anime: Anime) -> RenameProposal | None:
    """The rename-queue entry for one anime, if it has one -- computed for
    just this anime rather than by filtering the full library pass, since the
    series page asks for exactly one. Unlike the queue listing it also names
    each file, so the user can see what would happen before confirming.

    `anime` must have `expected_episodes` loaded (AnimeRepo.get does)."""
    if anime.ident_status != "identified" or anime.anidb_id is None or not has_known_variants(anime):
        return None
    local_episodes = await LocalEpisodeRepo(session).by_anime(anime.id)
    if not local_episodes:
        return None
    folder_order = await get_folder_title_order(session)
    plan = _compute_rename_plan(
        anime.directory_path, title_for(anime, folder_order), local_episodes, anime.expected_episodes
    )
    if not plan.dir_needs_rename and not plan.file_renames:
        return None
    return RenameProposal(
        current_dir_name=Path(anime.directory_path).name,
        target_dir_name=plan.target_dir_name,
        dir_needs_rename=plan.dir_needs_rename,
        file_renames=sorted(
            (os.path.basename(local.file_path), target) for local, target in plan.file_renames
        ),
    )


async def sort_proposal_for(session: AsyncSession, anime: Anime) -> SortQueueEntry | None:
    """The sort-queue entry for one anime, if it has one -- same single-anime
    reasoning as `rename_proposal_for`."""
    if anime.ident_status != "identified" or anime.anidb_id is None:
        return None
    folder = await session.get(Folder, anime.folder_id)
    if folder is None or folder.type != "download":
        return None
    local_episodes = await LocalEpisodeRepo(session).by_anime(anime.id)
    if not local_episodes:
        return None
    matches = match_local_episodes(local_episodes, anime.expected_episodes)
    suggestions = await _suggested_target_folders(session, {anime.anidb_id})
    return SortQueueEntry(
        anime_id=anime.id,
        title=anime.title,
        directory_path=anime.directory_path,
        anidb_id=anime.anidb_id,
        episode_count=len(local_episodes),
        matched_count=sum(1 for _, expected in matches if expected is not None),
        suggested_target_folder_id=suggestions.get(anime.anidb_id),
    )


async def maybe_auto_rename(session: AsyncSession, event_bus: EventBus, anime_id: int) -> None:
    """Unlike sorting, renaming never has a target-folder ambiguity to worry
    about, so "auto" mode can always act immediately once enabled."""
    if await get_rename_mode(session) != "auto":
        return
    try:
        await rename_anime(session, event_bus, anime_id)
    except RenameConflict:
        logger.info("auto_rename_deferred", anime_id=anime_id)
