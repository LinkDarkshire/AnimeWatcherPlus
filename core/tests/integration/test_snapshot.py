from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.config import Settings, get_settings
from app.services.snapshot import (
    PENDING_MAPPINGS,
    PENDING_SNAPSHOT,
    PathMapping,
    SnapshotError,
    apply_pending_import,
    create_snapshot,
    import_snapshot,
    map_path,
)

CORE_DIR = Path(__file__).resolve().parents[2]


def _migrated(data_dir: Path, monkeypatch) -> Settings:
    """A data directory with a database at the current schema, as the app creates it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AWP_DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    try:
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()
    return Settings(data_dir=data_dir)


def _fill_desktop_library(settings: Settings) -> None:
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO folder (id, path, type, name, active, offline, created_at) VALUES "
                   "(1, '/var/mnt/nas/media/Anime', 'content', 'Anime', 1, 0, '2026-01-01'),"
                   "(2, '/home/me/Local', 'content', 'Local', 1, 0, '2026-01-01')")
        db.execute("INSERT INTO anime (id, folder_id, directory_path, title, alt_titles, ident_status, is_duplicate, "
                   "no_scan, created_at) VALUES (1, 1, '/var/mnt/nas/media/Anime/Frieren', 'Frieren', '[]', "
                   "'identified', 0, 0, '2026-01-01')")
        db.execute("INSERT INTO local_episode (anime_id, file_path, ep_number, file_size, file_mtime, manual_override) "
                   "VALUES (1, '/var/mnt/nas/media/Anime/Frieren/Frieren - 01.mkv', '1', 1, 1.0, 0)")
        db.execute("INSERT INTO anime_search_fts (anime_id, title, alt_titles_text) VALUES (1, 'Frieren', '')")
        db.execute("INSERT INTO setting (key, value) VALUES ('sort_mode', '\"auto\"'), "
                   "('kept_empty_dirs', '[\"/var/mnt/nas/media/Anime/Empty\"]')")
        db.execute("INSERT INTO anidb_title_index (aid, title, lang, title_type) VALUES (1, 'Sousou no Frieren', 'x-jat', 'main')")
        db.execute("INSERT INTO device (name, public_key, is_admin, created_at) VALUES ('desktop-side', 'AAA=', 1, '2026-01-01')")
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    (settings.plugins_dir / "my_source.py").write_text("# plugin\n", encoding="utf-8")
    cache = settings.data_dir / "cache" / "anidb"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "1.xml").write_text("<anime/>", encoding="utf-8")


# --- path mapping -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,mappings,expected",
    [
        ("/var/mnt/nas/media/Anime/A/ep.mkv", [("/var/mnt/nas/media", "/media")], "/media/Anime/A/ep.mkv"),
        ("Z:\\Anime\\A\\ep.mkv", [("Z:\\Anime", "/media/Anime")], "/media/Anime/A/ep.mkv"),
        ("/media/Anime/A/ep.mkv", [("/media/Anime", "Z:\\Anime")], "Z:\\Anime\\A\\ep.mkv"),
        ("/media/Anime", [("/media/Anime/", "/data/Anime")], "/data/Anime"),
        # The longest matching prefix wins.
        ("/media/Anime/H/x", [("/media", "/a"), ("/media/Anime/H", "/b")], "/b/x"),
        # A prefix only matches whole path segments.
        ("/media/AnimeOld/x", [("/media/Anime", "/a")], None),
        ("/elsewhere/x", [("/media", "/a")], None),
    ],
)
def test_map_path(path: str, mappings: list[tuple[str, str]], expected: str | None) -> None:
    assert map_path(path, [PathMapping(s, t) for s, t in mappings]) == expected


# --- export / import ------------------------------------------------------------------------


def test_snapshot_moves_library_keeps_devices_and_maps_paths(tmp_path, monkeypatch) -> None:
    desktop = _migrated(tmp_path / "desktop", monkeypatch)
    server = _migrated(tmp_path / "server", monkeypatch)
    _fill_desktop_library(desktop)
    with sqlite3.connect(server.db_path) as db:
        db.execute("INSERT INTO device (name, public_key, is_admin, created_at) VALUES ('server-admin', 'BBB=', 1, '2026-01-01')")

    zip_path = create_snapshot(desktop, tmp_path / "snap.zip")
    result = import_snapshot(server, zip_path, [PathMapping("/var/mnt/nas/media", "/media")])

    assert result.plugins == 1 and result.cache_files == 1
    assert result.unmapped_folders == ["/home/me/Local"]
    with sqlite3.connect(server.db_path) as db:
        assert db.execute("SELECT path FROM folder ORDER BY id").fetchall() == [("/media/Anime",), ("/home/me/Local",)]
        assert db.execute("SELECT directory_path FROM anime").fetchone() == ("/media/Anime/Frieren",)
        assert db.execute("SELECT file_path FROM local_episode").fetchone() == ("/media/Anime/Frieren/Frieren - 01.mkv",)
        assert json.loads(db.execute("SELECT value FROM setting WHERE key='kept_empty_dirs'").fetchone()[0]) == [
            "/media/Anime/Empty"
        ]
        # The server's own paired devices survive; the snapshot's aren't copied.
        assert db.execute("SELECT name FROM device").fetchall() == [("server-admin",)]
        # Both search indexes work after the import.
        assert db.execute("SELECT anime_id FROM anime_search_fts WHERE anime_search_fts MATCH 'Frieren'").fetchall() == [(1,)]
        assert db.execute("SELECT rowid FROM anidb_title_fts WHERE anidb_title_fts MATCH 'Sousou'").fetchall()
    assert (server.plugins_dir / "my_source.py").exists()
    assert (server.data_dir / "cache" / "anidb" / "1.xml").exists()


def test_snapshot_from_another_schema_version_changes_nothing(tmp_path, monkeypatch) -> None:
    desktop = _migrated(tmp_path / "desktop", monkeypatch)
    server = _migrated(tmp_path / "server", monkeypatch)
    _fill_desktop_library(desktop)
    zip_path = create_snapshot(desktop, tmp_path / "snap.zip")
    with sqlite3.connect(server.db_path) as db:
        db.execute("UPDATE alembic_version SET version_num = 'something-else'")

    with pytest.raises(SnapshotError, match="Datenbank-Versionen"):
        import_snapshot(server, zip_path, [])
    with sqlite3.connect(server.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM anime").fetchone()[0] == 0


def test_not_a_snapshot(tmp_path, monkeypatch) -> None:
    server = _migrated(tmp_path / "server", monkeypatch)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(SnapshotError, match="kein gültiger"):
        import_snapshot(server, junk, [])


def test_pending_import_is_applied_once_with_a_backup(tmp_path, monkeypatch) -> None:
    server = _migrated(tmp_path / "server", monkeypatch)
    desktop = _migrated(tmp_path / "desktop", monkeypatch)
    _fill_desktop_library(server)  # the "server" library, moving back to the desktop
    create_snapshot(server, desktop.data_dir / PENDING_SNAPSHOT)
    (desktop.data_dir / PENDING_MAPPINGS).write_text(
        json.dumps([{"source": "/var/mnt/nas/media", "target": "Z:\\Media"}]), encoding="utf-8"
    )

    result = apply_pending_import(desktop)

    assert result is not None and result.rows > 0
    with sqlite3.connect(desktop.db_path) as db:
        assert db.execute("SELECT directory_path FROM anime").fetchone() == ("Z:\\Media\\Anime\\Frieren",)
    assert list(desktop.data_dir.glob("library.before-import-*.db"))
    assert not (desktop.data_dir / PENDING_SNAPSHOT).exists()
    assert apply_pending_import(desktop) is None  # not applied twice
