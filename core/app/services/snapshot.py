"""Moving a library between the desktop app's own core and a server.

A snapshot is a zip with a consistent copy of the database, the download
plugins and the AniDB response cache (so the new side doesn't have to ask
AniDB for everything again). Importing replaces the library in the running
database table by table -- except the server's paired devices -- and
rewrites folder paths, since the server sees the files under different
paths than the desktop.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

import structlog

from app import __version__
from app.config import Settings

logger = structlog.get_logger(__name__)

SNAPSHOT_FORMAT = 1
DB_NAME = "library.db"
META_NAME = "snapshot.json"

# Never copied: the paired devices belong to the server they were paired
# with, and the schema version is checked instead of copied.
_KEEP_TABLES = {"device", "alembic_version"}
# Paths that need rewriting when the library moves: (table, id column, path column).
_PATH_COLUMNS = [
    ("folder", "id", "path"),
    ("anime", "id", "directory_path"),
    ("local_episode", "id", "file_path"),
]


class SnapshotError(Exception):
    """The snapshot can't be imported; the message is meant for the user."""


@dataclass
class PathMapping:
    """`source` (as the old side saw it) becomes `target` (as the new side
    sees it), e.g. /var/mnt/nas/media/Anime -> /media/Anime."""

    source: str
    target: str


@dataclass
class ImportResult:
    tables: int = 0
    rows: int = 0
    plugins: int = 0
    cache_files: int = 0
    # Library folders no mapping applied to -- they'll likely show as
    # offline on the new side until mapped or re-added.
    unmapped_folders: list[str] = field(default_factory=list)


# --- Paths ------------------------------------------------------------------------


def _is_windows_style(path: str) -> bool:
    return (len(path) >= 2 and path[1] == ":") or path.startswith("\\\\")


def map_path(path: str, mappings: list[PathMapping]) -> str | None:
    """`path` rewritten by the longest matching mapping, separators adapted
    to the target's style (Windows "Z:\\Anime" <-> Linux "/media/Anime").
    None if no mapping applies."""
    for mapping in sorted(mappings, key=lambda m: len(m.source), reverse=True):
        source = mapping.source.rstrip("/\\")
        if not source:
            continue
        if path != source and not (path.startswith(source + "/") or path.startswith(source + "\\")):
            continue
        rest = path[len(source):]
        target = mapping.target.rstrip("/\\")
        if _is_windows_style(target):
            return str(PureWindowsPath(target + rest.replace("/", "\\")))
        return str(PurePosixPath(target + rest.replace("\\", "/")))
    return None


# --- Export --------------------------------------------------------------------------


def _schema_revision(conn: sqlite3.Connection, schema: str = "main") -> str | None:
    row = conn.execute(f"SELECT version_num FROM {schema}.alembic_version").fetchone()
    return row[0] if row else None


def create_snapshot(settings: Settings, destination: Path) -> Path:
    """Writes a snapshot zip of this core's library to `destination`."""
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / DB_NAME
        # SQLite's backup API gives a consistent copy while the app keeps running.
        with sqlite3.connect(settings.db_path) as source, sqlite3.connect(db_copy) as target:
            source.backup(target)
            revision = _schema_revision(target)
        meta = {
            "format": SNAPSHOT_FORMAT,
            "app_version": __version__,
            "schema_revision": revision,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
        }
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(META_NAME, json.dumps(meta))
            archive.write(db_copy, DB_NAME)
            for plugin in sorted(settings.plugins_dir.glob("*.py")):
                archive.write(plugin, f"plugins/{plugin.name}")
            cache = settings.data_dir / "cache" / "anidb"
            for cached in sorted(cache.glob("*.xml")):
                archive.write(cached, f"cache/anidb/{cached.name}")
    logger.info("snapshot_created", path=str(destination))
    return destination


# --- Import --------------------------------------------------------------------------


def _library_tables(conn: sqlite3.Connection, schema: str) -> list[str]:
    rows = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    # Full-text index tables (and their internal shadow tables) are rebuilt,
    # not copied.
    return sorted(name for (name,) in rows if "_fts" not in name and name not in _KEEP_TABLES)


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info('{table}')")]


def library_is_empty(db_path: Path) -> bool:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM anime").fetchone()[0] == 0


def import_snapshot(settings: Settings, snapshot: Path, mappings: list[PathMapping]) -> ImportResult:
    """Replaces this core's library with the snapshot's. Paired devices are
    kept. Runs in one transaction: on any error nothing has changed."""
    result = ImportResult()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(snapshot) as archive:
                meta = json.loads(archive.read(META_NAME))
                archive.extract(DB_NAME, tmp)
                members = archive.namelist()
                if meta.get("format") != SNAPSHOT_FORMAT:
                    raise SnapshotError("Unbekanntes Snapshot-Format")
                incoming = Path(tmp) / DB_NAME

                conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
                try:
                    _import_database(conn, incoming, mappings, result)
                finally:
                    conn.close()

                settings.plugins_dir.mkdir(parents=True, exist_ok=True)
                cache = settings.data_dir / "cache" / "anidb"
                cache.mkdir(parents=True, exist_ok=True)
                for name in members:
                    if name.startswith("plugins/") and name.endswith(".py"):
                        (settings.plugins_dir / Path(name).name).write_bytes(archive.read(name))
                        result.plugins += 1
                    elif name.startswith("cache/anidb/") and name.endswith(".xml"):
                        (cache / Path(name).name).write_bytes(archive.read(name))
                        result.cache_files += 1
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise SnapshotError("Die Datei ist kein gültiger AnimeWatcherPlus-Snapshot") from exc
    logger.info("snapshot_imported", **{k: v for k, v in vars(result).items() if k != "unmapped_folders"})
    return result


def _import_database(
    conn: sqlite3.Connection, incoming: Path, mappings: list[PathMapping], result: ImportResult
) -> None:
    conn.execute("ATTACH DATABASE ? AS incoming", (str(incoming),))
    try:
        if _schema_revision(conn, "incoming") != _schema_revision(conn, "main"):
            raise SnapshotError(
                "Snapshot und Ziel haben verschiedene Datenbank-Versionen -- beide Seiten auf dieselbe "
                "App-Version bringen"
            )
        tables = _library_tables(conn, "incoming")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in tables:
                columns = _columns(conn, "main", table)
                if columns != _columns(conn, "incoming", table):
                    raise SnapshotError(f"Tabelle '{table}' passt nicht zusammen")
                column_list = ", ".join(f'"{c}"' for c in columns)
                conn.execute(f'DELETE FROM main."{table}"')
                cursor = conn.execute(
                    f'INSERT INTO main."{table}" ({column_list}) SELECT {column_list} FROM incoming."{table}"'
                )
                result.tables += 1
                result.rows += max(cursor.rowcount, 0)
            # The anime search index has no triggers; copy it over as well.
            conn.execute("DELETE FROM main.anime_search_fts")
            conn.execute("INSERT INTO main.anime_search_fts SELECT * FROM incoming.anime_search_fts")
            _rewrite_paths(conn, mappings, result)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
    finally:
        conn.execute("DETACH DATABASE incoming")


def _rewrite_paths(conn: sqlite3.Connection, mappings: list[PathMapping], result: ImportResult) -> None:
    for table, id_column, column in _PATH_COLUMNS:
        for row_id, path in conn.execute(f'SELECT "{id_column}", "{column}" FROM main."{table}"').fetchall():
            mapped = map_path(path, mappings)
            if mapped is None:
                if table == "folder":
                    result.unmapped_folders.append(path)
                continue
            conn.execute(f'UPDATE main."{table}" SET "{column}" = ? WHERE "{id_column}" = ?', (mapped, row_id))
    # Directories the user chose to keep, remembered by path.
    row = conn.execute("SELECT value FROM main.setting WHERE key = 'kept_empty_dirs'").fetchone()
    if row and row[0]:
        kept = json.loads(row[0])
        if isinstance(kept, list):
            mapped_kept = [map_path(p, mappings) or p for p in kept if isinstance(p, str)]
            conn.execute(
                "UPDATE main.setting SET value = ? WHERE key = 'kept_empty_dirs'", (json.dumps(sorted(mapped_kept)),)
            )


# --- Pending import (desktop) ---------------------------------------------------------

PENDING_SNAPSHOT = "pending-import.zip"
PENDING_MAPPINGS = "pending-import.json"


def apply_pending_import(settings: Settings) -> ImportResult | None:
    """Switching the desktop app from a server back to local data stores the
    server's snapshot in the data directory and restarts the app; the local
    core applies it here, at startup, before anything else touches the
    library. The previous local database is kept as a backup."""
    snapshot = settings.data_dir / PENDING_SNAPSHOT
    if not snapshot.exists():
        return None
    mappings_file = settings.data_dir / PENDING_MAPPINGS
    raw = json.loads(mappings_file.read_text(encoding="utf-8")) if mappings_file.exists() else []
    mappings = [PathMapping(source=m["source"], target=m["target"]) for m in raw]
    backup = settings.data_dir / f"library.before-import-{dt.datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(settings.db_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    try:
        return import_snapshot(settings, snapshot, mappings)
    finally:
        # Applied or not, don't retry on every start; keep the file for a look.
        snapshot.replace(snapshot.with_suffix(".done.zip"))
        mappings_file.unlink(missing_ok=True)

