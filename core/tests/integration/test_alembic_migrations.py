from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

CORE_DIR = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_head_from_empty(tmp_path, monkeypatch) -> None:
    """Kap. 10: 'Alembic leer -> head' must succeed against a brand-new DB file."""
    monkeypatch.setenv("AWP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))

    try:
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()

    db_path = tmp_path / "library.db"
    assert db_path.exists()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()

    for expected in ("folder", "anime", "tag", "anidb_title_index", "anime_search_fts"):
        assert expected in tables


def test_migrated_anime_table_allows_duplicate_anidb_id(tmp_path, monkeypatch) -> None:
    """Regression guard at the schema level (see d85726b57997): a real
    Alembic-migrated DB, not just the test conftest's Base.metadata.create_all
    shortcut, must accept two anime rows sharing an anidb_id (FA-29).
    """
    monkeypatch.setenv("AWP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    try:
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()

    import sqlite3

    conn = sqlite3.connect(tmp_path / "library.db")
    try:
        conn.execute(
            "INSERT INTO folder (path, type, name, active, offline, created_at) "
            "VALUES ('/tmp/x', 'content', 'x', 1, 0, datetime('now'))"
        )
        folder_id = conn.execute("SELECT id FROM folder").fetchone()[0]
        for path in ("/tmp/x/A", "/tmp/x/B"):
            conn.execute(
                "INSERT INTO anime (folder_id, directory_path, anidb_id, title, alt_titles, "
                "ident_status, missing_on_disk, created_at, is_duplicate) "
                "VALUES (?, ?, 555, 'Same', '[]', 'identified', 0, datetime('now'), 0)",
                (folder_id, path),
            )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM anime WHERE anidb_id = 555").fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_migration_self_heals_a_db_stuck_with_the_old_unique_constraint(tmp_path, monkeypatch) -> None:
    """Regression test for a real-world report: a live library.db had
    `alembic_version` recorded as d85726b57997 (the revision meant to drop
    the UNIQUE(anidb_id) constraint) while the actual table still enforced
    it -- most likely two processes (a `cargo tauri dev` sidecar and a
    manually started `uvicorn`) migrating the same SQLite file concurrently.
    280262530db1 re-checks the *live* schema regardless of what alembic_version
    claims, and must heal this without losing data.
    """
    monkeypatch.setenv("AWP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    import sqlite3

    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE folder (id INTEGER PRIMARY KEY, path VARCHAR, type VARCHAR, name VARCHAR,
            active BOOLEAN, offline BOOLEAN, created_at DATETIME);
        CREATE TABLE anime (
            id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            directory_path VARCHAR NOT NULL,
            anidb_id INTEGER,
            title VARCHAR NOT NULL,
            original_title VARCHAR,
            alt_titles JSON NOT NULL,
            year INTEGER,
            media_type VARCHAR,
            description TEXT,
            poster_path VARCHAR,
            ident_status VARCHAR NOT NULL,
            match_score FLOAT,
            episode_count_expected INTEGER,
            missing_on_disk BOOLEAN NOT NULL,
            last_metadata_refresh DATETIME,
            created_at DATETIME NOT NULL,
            review_candidates JSON,
            is_duplicate BOOLEAN DEFAULT 0 NOT NULL,
            duplicate_of_anime_id INTEGER,
            PRIMARY KEY (id),
            UNIQUE (directory_path),
            UNIQUE (anidb_id),
            FOREIGN KEY(folder_id) REFERENCES folder (id),
            FOREIGN KEY(duplicate_of_anime_id) REFERENCES anime (id)
        );
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('d85726b57997');
        INSERT INTO folder (id, path, type, name, active, offline, created_at)
            VALUES (1, '/x', 'content', 'x', 1, 0, datetime('now'));
        INSERT INTO anime (id, folder_id, directory_path, anidb_id, title, alt_titles,
            ident_status, missing_on_disk, created_at, is_duplicate)
            VALUES (1, 1, '/x/A', 555, 'Show A', '[]', 'identified', 0, datetime('now'), 0);
        """
    )
    conn.commit()
    conn.close()

    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    try:
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()

    conn = sqlite3.connect(db_path)
    try:
        # Pre-existing data survived the rebuild.
        assert conn.execute("SELECT id, anidb_id, title FROM anime").fetchall() == [(1, 555, "Show A")]

        # The constraint is actually gone now, not just "supposed to be".
        conn.execute(
            "INSERT INTO anime (id, folder_id, directory_path, anidb_id, title, alt_titles, "
            "ident_status, missing_on_disk, created_at, is_duplicate) "
            "VALUES (2, 1, '/x/B', 555, 'Show B', '[]', 'identified', 0, datetime('now'), 1)"
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM anime WHERE anidb_id = 555").fetchone()[0] == 2
    finally:
        conn.close()
