from __future__ import annotations

import errno
from pathlib import Path

import pytest

from app.db.models import Anime, ExpectedEpisode, Setting
from app.db.repositories import AnimeRepo, FolderRepo, LocalEpisodeRepo
from app.services import sorter
from app.services.jobs import EventBus
from app.services.settings_store import FOLDER_TITLE_ORDER, RENAME_MODE, SORT_MODE


async def _make_download_anime(
    session, folder_id: int, directory: Path, anidb_id: int, ep_numbers: list[int]
) -> Anime:
    """Identified anime living in a download folder, with one ExpectedEpisode
    + one real local file per number in `ep_numbers` (fully matched by
    default -- tests create partial-match scenarios by deleting/renaming a
    LocalEpisode row afterwards)."""
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
        file_path = directory / f"[Group] {directory.name} - {ep:02d} [1080p].mkv"
        file_path.write_bytes(b"x" * 100)
        await episode_repo.upsert(anime.id, str(file_path), 100, file_path.stat().st_mtime, str(ep))

    return await AnimeRepo(session).get(anime.id)


async def _make_content_anime(session, folder_id: int, directory: Path, anidb_id: int, title: str) -> Anime:
    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), title)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = title
    anime.title_main = title
    await session.commit()
    return anime


async def _make_mismatched_anime(
    session,
    folder_id: int,
    directory: Path,
    anidb_id: int,
    title: str,
    ep_numbers: list[int],
    ep_titles: list[str | None] | None = None,
) -> Anime:
    """Anime whose directory name and episode filenames deliberately don't
    follow the canonical rename scheme -- the directory keeps whatever name
    it's given (independent of `title`), and episode files use an
    old-style name, so rename_anime always has something to do."""
    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = title
    anime.title_main = title
    for i, ep in enumerate(ep_numbers):
        ep_title = ep_titles[i] if ep_titles else None
        session.add(ExpectedEpisode(anime_id=anime.id, ep_number=str(ep), title=ep_title))
    await session.commit()

    episode_repo = LocalEpisodeRepo(session)
    for ep in ep_numbers:
        file_path = directory / f"OldName - {ep:02d}.mkv"
        file_path.write_bytes(b"x" * 10)
        await episode_repo.upsert(anime.id, str(file_path), 10, file_path.stat().st_mtime, str(ep))

    return await AnimeRepo(session).get(anime.id)


def test_sanitize_filename_component_strips_invalid_chars() -> None:
    assert sorter.sanitize_filename_component('Re:Zero <Season 2> "Arc"') == "ReZero Season 2 Arc"
    assert sorter.sanitize_filename_component("Trailing dots.. ") == "Trailing dots"
    assert sorter.sanitize_filename_component("???") == "Unknown"


def test_build_episode_filename_always_uses_the_full_scheme() -> None:
    """"{Title} - S01E{episode} - {episode name}", with a generic name when
    the provider lists none -- the shape must not vary between episodes of
    the same series."""
    assert (
        sorter.build_episode_filename("Attack on Titan", "5", "To You, in 2000 Years", ".mkv")
        == "Attack on Titan - S01E05 - To You, in 2000 Years.mkv"
    )
    assert sorter.build_episode_filename("Show", "12", None, ".mp4") == "Show - S01E12 - Episode 12.mp4"
    assert sorter.build_episode_filename("Show", "05", None, ".mkv") == "Show - S01E05 - Episode 5.mkv"


def test_build_episode_filename_includes_sanitized_episode_title() -> None:
    assert (
        sorter.build_episode_filename("Show", "3", "A New Beginning", ".mkv")
        == "Show - S01E03 - A New Beginning.mkv"
    )
    assert (
        sorter.build_episode_filename("Show", "4", 'Trouble: Part "One"', ".mkv")
        == "Show - S01E04 - Trouble Part One.mkv"
    )


def test_match_local_episodes_ignores_prefixed_specials() -> None:
    local = [_local_ep(1, "5"), _local_ep(2, None)]
    expected = [_expected_ep("05"), _expected_ep("S1")]
    matches = sorter.match_local_episodes(local, expected)
    assert matches[0][1] is not None
    assert matches[0][1].ep_number == "05"
    assert matches[1][1] is None


def _local_ep(id_: int, ep_number: str | None):
    from app.db.models import LocalEpisode

    return LocalEpisode(id=id_, anime_id=1, file_path=f"/x/{id_}.mkv", ep_number=ep_number)


def _expected_ep(ep_number: str):
    return ExpectedEpisode(anime_id=1, ep_number=ep_number)


def test_move_file_same_volume_rename(tmp_path) -> None:
    src = tmp_path / "src.mkv"
    src.write_bytes(b"hello")
    dest = tmp_path / "sub" / "dest.mkv"

    result = sorter.move_file(src, dest)

    assert result == dest
    assert dest.read_bytes() == b"hello"
    assert not src.exists()


def test_move_file_dedupes_on_collision(tmp_path) -> None:
    src = tmp_path / "src.mkv"
    src.write_bytes(b"new")
    dest = tmp_path / "dest.mkv"
    dest.write_bytes(b"existing")

    result = sorter.move_file(src, dest)

    assert result == tmp_path / "dest (2).mkv"
    assert dest.read_bytes() == b"existing"  # original never overwritten
    assert result.read_bytes() == b"new"


def test_move_file_cross_device_fallback(tmp_path, monkeypatch) -> None:
    src = tmp_path / "src.mkv"
    src.write_bytes(b"payload")
    dest = tmp_path / "dest.mkv"

    def fake_rename(self, target):
        raise OSError(errno.EXDEV, "simulated cross-device rename failure")

    monkeypatch.setattr(Path, "rename", fake_rename)

    result = sorter.move_file(src, dest)

    assert result == dest
    assert dest.read_bytes() == b"payload"
    assert not src.exists()


def test_move_file_reraises_a_locked_source_instead_of_copying(tmp_path, monkeypatch) -> None:
    """Only a cross-device move may fall back to copying. A locked or
    unreadable source used to be copied and then fail to delete, leaving the
    episode on disk twice."""
    src = tmp_path / "src.mkv"
    src.write_bytes(b"payload")
    dest = tmp_path / "sub" / "dest.mkv"

    def fake_rename(self, target):
        raise PermissionError(errno.EACCES, "file is open in another program")

    monkeypatch.setattr(Path, "rename", fake_rename)

    with pytest.raises(PermissionError):
        sorter.move_file(src, dest)

    assert src.read_bytes() == b"payload"
    assert not dest.exists()


def test_move_file_removes_the_copy_when_the_source_cannot_be_deleted(tmp_path, monkeypatch) -> None:
    """A verified copy whose source won't go must not leave a duplicate --
    the move is all-or-nothing."""
    src = tmp_path / "src.mkv"
    src.write_bytes(b"payload")
    dest = tmp_path / "dest.mkv"

    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(OSError(errno.EXDEV, "x")))
    monkeypatch.setattr(Path, "unlink", lambda self, **kw: (_ for _ in ()).throw(PermissionError("locked")))

    with pytest.raises(PermissionError):
        sorter.move_file(src, dest)

    assert src.exists()


def test_move_file_performs_a_case_only_rename(tmp_path) -> None:
    """On a case-insensitive filesystem the target of a pure casing fix
    "already exists" -- it is the very file being renamed. Treating that as a
    collision produced a "Name (2).mkv" duplicate instead."""
    src = tmp_path / "show - s01e01.mkv"
    src.write_bytes(b"x")

    result = sorter.move_file(src, tmp_path / "Show - S01E01.mkv")

    assert result.name == "Show - S01E01.mkv"
    assert [p.name for p in tmp_path.iterdir()] == ["Show - S01E01.mkv"]


def test_move_episode_file_takes_the_nfo_along(tmp_path) -> None:
    """Otherwise the old `.nfo` stays behind next to the renamed video and
    Jellyfin reads it as a separate episode."""
    src = tmp_path / "Old Name.mkv"
    src.write_bytes(b"video")
    (tmp_path / "Old Name.nfo").write_text("<episodedetails/>", encoding="utf-8")

    result = sorter.move_episode_file(src, tmp_path / "New Name.mkv")

    assert result.name == "New Name.mkv"
    assert (tmp_path / "New Name.nfo").exists()
    assert not (tmp_path / "Old Name.nfo").exists()


@pytest.mark.asyncio
async def test_sort_anime_merge_full_match_deletes_source(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")

    target = await _make_content_anime(db_session, content_folder.id, tmp_path / "content" / "Show A", 42, "Show A")
    source = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show A", 42, [1, 2])
    source_dir = Path(source.directory_path)

    events: list[dict] = []

    async def collect(payload: dict) -> None:
        events.append(payload)

    bus = EventBus()
    bus.subscribe(collect)

    result = await sorter.sort_anime(db_session, bus, source.id, content_folder.id)

    assert result.moved == 2
    assert result.unmatched == 0
    assert result.target_anime_id == target.id
    assert (Path(target.directory_path) / "Show A - S01E01 - Episode 1.mkv").exists()
    assert (Path(target.directory_path) / "Show A - S01E02 - Episode 2.mkv").exists()
    assert not source_dir.exists()
    assert await AnimeRepo(db_session).get(source.id) is None

    event_names = [e["event"] for e in events]
    assert "anime.sorted" in event_names
    assert "anime.removed" in event_names


@pytest.mark.asyncio
async def test_sort_anime_merge_partial_match_keeps_source(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")

    target = await _make_content_anime(db_session, content_folder.id, tmp_path / "content" / "Show A", 42, "Show A")
    source = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show A", 42, [1])
    # An extra local file the provider doesn't know about (no ExpectedEpisode
    # for "99") -- must be left behind untouched.
    extra = Path(source.directory_path) / "extra.mkv"
    extra.write_bytes(b"y")
    await LocalEpisodeRepo(db_session).upsert(source.id, str(extra), 1, extra.stat().st_mtime, "99")

    bus = EventBus()
    result = await sorter.sort_anime(db_session, bus, source.id, content_folder.id)

    assert result.moved == 1
    assert result.unmatched == 1
    assert (Path(target.directory_path) / "Show A - S01E01 - Episode 1.mkv").exists()
    assert extra.exists()  # unmatched file never touched
    reloaded_source = await AnimeRepo(db_session).get(source.id)
    assert reloaded_source is not None  # source anime kept, dir not emptied


@pytest.mark.asyncio
async def test_sort_anime_relocate_full_match(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    source = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show B", 7, [1, 2])
    source_dir = Path(source.directory_path)
    (source_dir / "poster.jpg").write_bytes(b"img")

    bus = EventBus()
    result = await sorter.sort_anime(db_session, bus, source.id, content_folder.id)

    assert result.moved == 2
    assert result.target_anime_id == source.id
    new_dir = tmp_path / "content" / "Show B"
    assert (new_dir / "Show B - S01E01 - Episode 1.mkv").exists()
    assert (new_dir / "Show B - S01E02 - Episode 2.mkv").exists()
    assert (new_dir / "poster.jpg").exists()
    assert not source_dir.exists()

    reloaded = await AnimeRepo(db_session).get(source.id)
    assert reloaded.folder_id == content_folder.id
    assert reloaded.directory_path == str(new_dir)


@pytest.mark.asyncio
async def test_sort_anime_relocate_partial_match_raises_conflict(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    source = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show C", 9, [1])
    source_dir = Path(source.directory_path)
    unmatched = source_dir / "unmatched.mkv"
    unmatched.write_bytes(b"z")
    await LocalEpisodeRepo(db_session).upsert(source.id, str(unmatched), 1, unmatched.stat().st_mtime, "99")

    bus = EventBus()
    with pytest.raises(sorter.SortConflict):
        await sorter.sort_anime(db_session, bus, source.id, content_folder.id)

    # Nothing moved -- source untouched.
    assert source_dir.exists()
    assert list(source_dir.glob("*.mkv"))
    assert not (tmp_path / "content" / "Show C").exists()


@pytest.mark.asyncio
async def test_sort_anime_raises_conflict_when_nothing_matches(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    directory = tmp_path / "downloads" / "Show D"
    directory.mkdir(parents=True)
    anime = await AnimeRepo(db_session).create_pending(download_folder.id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = 11
    await db_session.commit()

    file_path = directory / "unknown.mkv"
    file_path.write_bytes(b"a")
    await LocalEpisodeRepo(db_session).upsert(anime.id, str(file_path), 1, file_path.stat().st_mtime, None)

    bus = EventBus()
    with pytest.raises(sorter.SortConflict):
        await sorter.sort_anime(db_session, bus, anime.id, content_folder.id)


@pytest.mark.asyncio
async def test_sort_anime_raises_conflict_when_no_local_episodes(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    directory = tmp_path / "downloads" / "Show E"
    directory.mkdir(parents=True)
    anime = await AnimeRepo(db_session).create_pending(download_folder.id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = 12
    await db_session.commit()

    bus = EventBus()
    with pytest.raises(sorter.SortConflict):
        await sorter.sort_anime(db_session, bus, anime.id, content_folder.id)


@pytest.mark.asyncio
async def test_list_sort_queue_filters_and_suggests_target(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")

    # Included: identified, in a download folder, has local episodes.
    included = await _make_download_anime(
        db_session, download_folder.id, tmp_path / "downloads" / "Included", 100, [1, 2]
    )
    # Existing content-folder counterpart -> should be suggested as target.
    await _make_content_anime(db_session, content_folder.id, tmp_path / "content" / "Included", 100, "Included")

    # Excluded: not yet identified.
    pending_dir = tmp_path / "downloads" / "Pending"
    pending_dir.mkdir(parents=True)
    await AnimeRepo(db_session).create_pending(download_folder.id, str(pending_dir), "Pending")

    # Excluded: lives in a content folder.
    await _make_content_anime(db_session, content_folder.id, tmp_path / "content" / "InContent", 200, "InContent")

    # Excluded: identified, in a download folder, but zero local episodes.
    empty_dir = tmp_path / "downloads" / "NoFiles"
    empty_dir.mkdir(parents=True)
    empty_anime = await AnimeRepo(db_session).create_pending(download_folder.id, str(empty_dir), "NoFiles")
    empty_anime.ident_status = "identified"
    empty_anime.anidb_id = 300
    await db_session.commit()

    entries = await sorter.list_sort_queue(db_session)

    assert {e.anime_id for e in entries} == {included.id}
    entry = entries[0]
    assert entry.episode_count == 2
    assert entry.matched_count == 2
    assert entry.suggested_target_folder_id == content_folder.id


@pytest.mark.asyncio
async def test_maybe_auto_sort_single_content_folder_moves_immediately(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    db_session.add(Setting(key=SORT_MODE, value="auto"))
    await db_session.commit()

    anime = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show F", 55, [1])

    bus = EventBus()
    await sorter.maybe_auto_sort(db_session, bus, anime.id)

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.folder_id == content_folder.id
    assert (tmp_path / "content" / "Show F" / "Show F - S01E01 - Episode 1.mkv").exists()


@pytest.mark.asyncio
async def test_maybe_auto_sort_multiple_content_folders_defers(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    await FolderRepo(db_session).create(str(tmp_path / "content1"), "content", "Content 1")
    await FolderRepo(db_session).create(str(tmp_path / "content2"), "content", "Content 2")
    db_session.add(Setting(key=SORT_MODE, value="auto"))
    await db_session.commit()

    anime = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show G", 66, [1])
    original_dir = anime.directory_path

    bus = EventBus()
    await sorter.maybe_auto_sort(db_session, bus, anime.id)

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.directory_path == original_dir  # untouched, deferred to manual sort queue


@pytest.mark.asyncio
async def test_maybe_auto_sort_ask_mode_never_moves(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    # sort_mode defaults to "ask" -- no Setting row needed.

    anime = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show H", 77, [1])
    original_dir = anime.directory_path

    bus = EventBus()
    await sorter.maybe_auto_sort(db_session, bus, anime.id)

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.directory_path == original_dir


@pytest.mark.asyncio
async def test_maybe_auto_sort_merges_into_existing_target_even_with_multiple_content_folders(
    db_session, tmp_path
) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "downloads"), "download", "Downloads")
    content_folder_1 = await FolderRepo(db_session).create(str(tmp_path / "content1"), "content", "Content 1")
    await FolderRepo(db_session).create(str(tmp_path / "content2"), "content", "Content 2")
    db_session.add(Setting(key=SORT_MODE, value="auto"))
    await db_session.commit()

    target = await _make_content_anime(db_session, content_folder_1.id, tmp_path / "content1" / "Show I", 88, "Show I")
    anime = await _make_download_anime(db_session, download_folder.id, tmp_path / "downloads" / "Show I", 88, [1])

    bus = EventBus()
    await sorter.maybe_auto_sort(db_session, bus, anime.id)

    assert (Path(target.directory_path) / "Show I - S01E01 - Episode 1.mkv").exists()
    assert await AnimeRepo(db_session).get(anime.id) is None  # source merged away


@pytest.mark.asyncio
async def test_rename_anime_renames_dir_and_files(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 1, "Real Title", [1, 2],
        ep_titles=["First", "Second"],
    )
    old_dir = Path(anime.directory_path)
    (old_dir / "poster.jpg").write_bytes(b"img")
    (old_dir / "tvshow.nfo").write_text("<tvshow/>", encoding="utf-8")

    bus = EventBus()
    events: list[dict] = []

    async def collect(payload: dict) -> None:
        events.append(payload)

    bus.subscribe(collect)

    result = await sorter.rename_anime(db_session, bus, anime.id)

    assert result.renamed_dir is True
    assert result.renamed_files == 2
    new_dir = tmp_path / "content" / "Real Title"
    assert new_dir.exists()
    assert not old_dir.exists()
    assert (new_dir / "Real Title - S01E01 - First.mkv").exists()
    assert (new_dir / "Real Title - S01E02 - Second.mkv").exists()
    assert (new_dir / "poster.jpg").exists()  # sidecars travel with the dir rename
    assert (new_dir / "tvshow.nfo").exists()

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.directory_path == str(new_dir)
    local_episodes = await LocalEpisodeRepo(db_session).by_anime(anime.id)
    assert {Path(le.file_path).parent for le in local_episodes} == {new_dir}

    assert any(e["event"] == "anime.renamed" for e in events)


@pytest.mark.asyncio
async def test_rename_anime_dir_already_correct_only_renames_files(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "Real Title", 2, "Real Title", [1]
    )

    result = await sorter.rename_anime(db_session, EventBus(), anime.id)

    assert result.renamed_dir is False
    assert result.renamed_files == 1
    assert (Path(anime.directory_path) / "Real Title - S01E01 - Episode 1.mkv").exists()


@pytest.mark.asyncio
async def test_rename_anime_no_op_when_everything_matches(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Show A", 3, [1]
    )
    # _make_download_anime uses a "[Group] ... [1080p].mkv" style filename --
    # rename it to the already-canonical form first so there's nothing to do.
    old_file = next(Path(anime.directory_path).glob("*.mkv"))
    canonical = Path(anime.directory_path) / "Show A - S01E01 - Episode 1.mkv"
    old_file.rename(canonical)
    await LocalEpisodeRepo(db_session).delete_by_path(str(old_file))
    await LocalEpisodeRepo(db_session).upsert(anime.id, str(canonical), 1, canonical.stat().st_mtime, "1")

    result = await sorter.rename_anime(db_session, EventBus(), anime.id)

    assert result.renamed_dir is False
    assert result.renamed_files == 0


@pytest.mark.asyncio
async def test_rename_anime_raises_conflict_on_directory_collision(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    # An unrelated directory already sits at the target name.
    (tmp_path / "content" / "Real Title").mkdir(parents=True)
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 4, "Real Title", [1]
    )
    old_dir = Path(anime.directory_path)

    with pytest.raises(sorter.RenameConflict):
        await sorter.rename_anime(db_session, EventBus(), anime.id)

    assert old_dir.exists()  # nothing touched


@pytest.mark.asyncio
async def test_rename_anime_leaves_unmatched_files_untouched(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 5, "Real Title", [1]
    )
    old_dir = Path(anime.directory_path)
    extra = old_dir / "unmatched.mkv"
    extra.write_bytes(b"z")
    await LocalEpisodeRepo(db_session).upsert(anime.id, str(extra), 1, extra.stat().st_mtime, "99")

    result = await sorter.rename_anime(db_session, EventBus(), anime.id)

    assert result.renamed_dir is True
    assert result.renamed_files == 1
    new_dir = tmp_path / "content" / "Real Title"
    assert (new_dir / "unmatched.mkv").exists()  # moved with the dir, but not renamed


@pytest.mark.asyncio
async def test_list_rename_queue_filters_correctly(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")

    mismatched = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 10, "Real Title", [1, 2]
    )

    matching = await _make_download_anime(
        db_session, content_folder.id, tmp_path / "content" / "Matching", 11, [1]
    )
    old_file = next(Path(matching.directory_path).glob("*.mkv"))
    canonical = Path(matching.directory_path) / "Matching - S01E01 - Episode 1.mkv"
    old_file.rename(canonical)
    await LocalEpisodeRepo(db_session).delete_by_path(str(old_file))
    await LocalEpisodeRepo(db_session).upsert(matching.id, str(canonical), 1, canonical.stat().st_mtime, "1")
    matching.title = "Matching"
    matching.title_main = "Matching"
    await db_session.commit()

    entries = await sorter.list_rename_queue(db_session)

    assert {e.anime_id for e in entries} == {mismatched.id}
    entry = entries[0]
    assert entry.current_dir_name == "OldFolderName"
    assert entry.target_dir_name == "Real Title"
    assert entry.mismatched_file_count == 2
    assert entry.total_matched_episodes == 2


@pytest.mark.asyncio
async def test_rename_anime_fixes_a_case_only_directory_name(db_session, tmp_path) -> None:
    """On a case-insensitive filesystem the target of a pure casing fix
    "already exists" -- it's the same directory. Treating that as a collision
    left the anime stuck in the rename queue with every resolve returning
    409."""
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "real title", 40, "Real Title", [1]
    )

    result = await sorter.rename_anime(db_session, EventBus(), anime.id)

    assert result.renamed_dir is True
    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert Path(reloaded.directory_path).name == "Real Title"
    assert await sorter.list_rename_queue(db_session) == []


@pytest.mark.asyncio
async def test_rename_anime_still_refuses_a_genuine_directory_collision(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 41, "Real Title", [1]
    )
    (tmp_path / "content" / "Real Title").mkdir(parents=True)

    with pytest.raises(sorter.RenameConflict):
        await sorter.rename_anime(db_session, EventBus(), anime.id)


@pytest.mark.asyncio
async def test_rename_anime_uses_the_folder_title_order_not_the_display_title(db_session, tmp_path) -> None:
    """The two orders are independent: `anime.title` is the display name
    resolved from `display_title_order`, while what lands on disk follows
    `folder_title_order`."""
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    db_session.add(Setting(key=FOLDER_TITLE_ORDER, value=["main", "en", "ja"]))
    await db_session.commit()

    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 30, "English Title", [1]
    )
    anime.title_main = "Romaji Title"
    anime.title_en = "English Title"
    await db_session.commit()

    result = await sorter.rename_anime(db_session, EventBus(), anime.id)

    assert result.renamed_dir is True
    new_dir = tmp_path / "content" / "Romaji Title"
    assert new_dir.exists()
    assert (new_dir / "Romaji Title - S01E01 - Episode 1.mkv").exists()

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.directory_path == str(new_dir)
    assert reloaded.title == "English Title"  # display name untouched by a folder rename


@pytest.mark.asyncio
async def test_list_rename_queue_targets_the_folder_title_order(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    db_session.add(Setting(key=FOLDER_TITLE_ORDER, value=["ja", "main", "en"]))
    await db_session.commit()

    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 31, "English Title", [1]
    )
    anime.title_ja = "日本語タイトル"
    anime.title_en = "English Title"
    await db_session.commit()

    entries = await sorter.list_rename_queue(db_session)

    assert [e.target_dir_name for e in entries] == ["日本語タイトル"]


@pytest.mark.asyncio
async def test_sort_anime_names_the_new_directory_by_the_folder_title_order(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "dl"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    (tmp_path / "content").mkdir(parents=True, exist_ok=True)
    db_session.add(Setting(key=FOLDER_TITLE_ORDER, value=["main", "en", "ja"]))
    await db_session.commit()

    anime = await _make_download_anime(db_session, download_folder.id, tmp_path / "dl" / "Raw", 32, [1])
    anime.title = "English Title"
    anime.title_main = "Romaji Title"
    anime.title_en = "English Title"
    await db_session.commit()

    result = await sorter.sort_anime(db_session, EventBus(), anime.id, content_folder.id)

    assert result.moved == 1
    new_dir = tmp_path / "content" / "Romaji Title"
    assert (new_dir / "Romaji Title - S01E01 - Episode 1.mkv").exists()


@pytest.mark.asyncio
async def test_maybe_auto_rename_auto_mode_renames_immediately(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    db_session.add(Setting(key=RENAME_MODE, value="auto"))
    await db_session.commit()

    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 20, "Real Title", [1]
    )

    await sorter.maybe_auto_rename(db_session, EventBus(), anime.id)

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.directory_path == str(tmp_path / "content" / "Real Title")


@pytest.mark.asyncio
async def test_maybe_auto_rename_ask_mode_never_renames(db_session, tmp_path) -> None:
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    # rename_mode defaults to "ask" -- no Setting row needed.

    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 21, "Real Title", [1]
    )
    original_dir = anime.directory_path

    await sorter.maybe_auto_rename(db_session, EventBus(), anime.id)

    reloaded = await AnimeRepo(db_session).get(anime.id)
    assert reloaded.directory_path == original_dir


@pytest.mark.asyncio
async def test_queue_counts_agree_with_the_listings(db_session, tmp_path) -> None:
    """The nav badge counts via SQL/flat selects while the Abfragen page lists
    via the full entries -- the two must never disagree, or the badge shows a
    number the page can't account for."""
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "dl"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")

    assert await sorter.count_sort_queue(db_session) == 0
    assert await sorter.count_rename_queue(db_session) == 0

    # Two sortable download animes, one of them also needing a rename.
    await _make_download_anime(db_session, download_folder.id, tmp_path / "dl" / "Show A", 50, [1, 2])
    await _make_download_anime(db_session, download_folder.id, tmp_path / "dl" / "Show B", 51, [1])
    # A content anime with a mismatched directory name (rename only, not sortable).
    await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldName", 52, "Real Title", [1]
    )
    # An identified anime without any local files shows up in neither queue.
    await _make_content_anime(db_session, content_folder.id, tmp_path / "content" / "Empty", 53, "Empty")

    assert await sorter.count_sort_queue(db_session) == len(await sorter.list_sort_queue(db_session)) == 2
    assert await sorter.count_rename_queue(db_session) == len(await sorter.list_rename_queue(db_session))
    assert await sorter.count_rename_queue(db_session) == 3


@pytest.mark.asyncio
async def test_list_sort_queue_suggests_an_existing_content_folder(db_session, tmp_path) -> None:
    """The suggestion used to be one query per entry; batching it must keep
    the same answers, including 'no suggestion' for an unknown anime."""
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "dl"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")

    await _make_content_anime(db_session, content_folder.id, tmp_path / "content" / "Known", 60, "Known")
    await _make_download_anime(db_session, download_folder.id, tmp_path / "dl" / "Known", 60, [1])
    await _make_download_anime(db_session, download_folder.id, tmp_path / "dl" / "Unknown", 61, [1])

    by_anidb = {e.anidb_id: e.suggested_target_folder_id for e in await sorter.list_sort_queue(db_session)}

    assert by_anidb[60] == content_folder.id
    assert by_anidb[61] is None


@pytest.mark.asyncio
async def test_anime_without_title_variants_is_never_renamed(db_session, tmp_path) -> None:
    """Without variants the only name available is the untagged legacy title
    -- in a real library that was Japanese script for 314 correctly romanized
    folders, all of which the rename queue then proposed to rename."""
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "Tsundero", 50, "ツンデロ", [1]
    )
    anime.title_main = None
    await db_session.commit()

    assert await sorter.list_rename_queue(db_session) == []
    assert await sorter.count_rename_queue(db_session) == 0
    with pytest.raises(sorter.RenameConflict):
        await sorter.rename_anime(db_session, EventBus(), anime.id)
    assert (tmp_path / "content" / "Tsundero").is_dir()  # untouched on disk


@pytest.mark.asyncio
async def test_queue_listings_are_alphabetical(db_session, tmp_path) -> None:
    download_folder = await FolderRepo(db_session).create(str(tmp_path / "dl"), "download", "Downloads")
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    for anidb_id, title in ((61, "zebra"), (62, "Apple"), (63, "mango")):
        await _make_mismatched_anime(
            db_session, content_folder.id, tmp_path / "content" / f"old {anidb_id}", anidb_id, title, [1]
        )
        await _make_download_anime(db_session, download_folder.id, tmp_path / "dl" / title, 100 + anidb_id, [1])

    rename_titles = [e.title for e in await sorter.list_rename_queue(db_session)]
    sort_titles = [e.title for e in await sorter.list_sort_queue(db_session)]

    # Case-insensitive: "Apple", "mango", "zebra" -- a binary sort would list
    # every uppercase title before every lowercase one. The download copies
    # show up in the rename queue too, since their filenames aren't in the
    # scheme.
    assert set(rename_titles) == {"Apple", "mango", "zebra"}
    assert rename_titles == sorted(rename_titles, key=str.casefold)
    assert sort_titles == ["Apple", "mango", "zebra"]


@pytest.mark.asyncio
async def test_rename_keeps_what_succeeded_when_one_file_is_locked(
    db_session, tmp_path, monkeypatch
) -> None:
    """A locked file must not leave the directory renamed, the rest of the
    files half-done and the DB pointing at paths that no longer exist."""
    content_folder = await FolderRepo(db_session).create(str(tmp_path / "content"), "content", "Content")
    anime = await _make_mismatched_anime(
        db_session, content_folder.id, tmp_path / "content" / "OldFolderName", 70, "Real Title", [1, 2, 3]
    )

    real_move = sorter.move_episode_file
    calls = {"n": 0}

    def flaky_move(src, dest):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError("file is open in another program")
        return real_move(src, dest)

    monkeypatch.setattr(sorter, "move_episode_file", flaky_move)

    with pytest.raises(sorter.RenameConflict):
        await sorter.rename_anime(db_session, EventBus(), anime.id)

    reloaded = await AnimeRepo(db_session).get(anime.id)
    episodes = await LocalEpisodeRepo(db_session).by_anime(anime.id)
    # Every recorded path must exist on disk, renamed or not.
    assert all(Path(e.file_path).exists() for e in episodes)
    assert Path(reloaded.directory_path).name == "Real Title"
