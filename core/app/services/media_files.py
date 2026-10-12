from __future__ import annotations

from pathlib import Path

from app.services.artwork import ANIINFO_FILENAME, POSTER_FILENAME
from app.services.nfo import TVSHOW_NFO

# Shared by the scanner and the sorter. Kept in its own module because the
# sorter is imported by identification, which the scanner imports -- so the
# sorter can't import these from the scanner without a cycle.

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".wmv", ".flv", ".mov"}
IGNORED_SUFFIXES = {".part", ".crdownload", ".!ut", ".tmp", ".downloading"}

# The per-anime files the app writes itself. A directory holding nothing but
# these has nothing of the user's left in it.
APP_SIDECARS = frozenset({POSTER_FILENAME, TVSHOW_NFO, ANIINFO_FILENAME})


def is_ignored(path: Path) -> bool:
    return path.suffix.lower() in IGNORED_SUFFIXES


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS and not is_ignored(path)


def has_video_files(directory: Path) -> bool:
    return any(f.is_file() and is_video_file(f) for f in directory.rglob("*"))


def has_user_files(directory: Path) -> bool:
    """Whether anything other than the app's own sidecars is left anywhere in
    the directory -- subtitles, fonts, archives, an in-progress `.part`
    download. "No video files" is not "empty": deleting on that basis would
    take all of those with it."""
    return any(f.is_file() and f.name not in APP_SIDECARS for f in directory.rglob("*"))


def companion_files(video: Path) -> list[Path]:
    """Files that belong to one episode by name: `Ep 01.nfo`, `Ep 01.ass`,
    `Ep 01.en.srt`, `Ep 01.mka`, ... They have to travel with the episode on
    every move or rename, or players stop associating them with it. Other
    video files are excluded -- `Ep 01.5.mkv` is an episode of its own."""
    prefix = video.stem.lower() + "."
    try:
        siblings = list(video.parent.iterdir())
    except OSError:
        return []
    return [
        p
        for p in siblings
        if p != video
        and p.name.lower().startswith(prefix)
        and p.suffix.lower() not in VIDEO_EXTENSIONS
        and p.is_file()
    ]


def remove_dir_if_empty(directory: Path) -> bool:
    """Deletes the directory tree only if no file is left anywhere in it
    (empty subdirectories don't count). Returns whether it is gone."""
    if not directory.exists():
        return True
    if any(f.is_file() for f in directory.rglob("*")):
        return False
    for sub in sorted((d for d in directory.rglob("*") if d.is_dir()), reverse=True):
        sub.rmdir()
    directory.rmdir()
    return True
