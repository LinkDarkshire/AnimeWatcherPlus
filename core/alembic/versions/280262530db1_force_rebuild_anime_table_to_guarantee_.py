"""force rebuild anime table to guarantee no unique index on anidb_id

Revision ID: 280262530db1
Revises: d85726b57997
Create Date: 2026-07-17 00:23:48.796358

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '280262530db1'
down_revision: Union[str, Sequence[str], None] = 'd85726b57997'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COPY_COLUMNS = (
    "id, folder_id, directory_path, anidb_id, title, original_title, alt_titles, "
    "year, media_type, description, poster_path, ident_status, match_score, "
    "episode_count_expected, missing_on_disk, last_metadata_refresh, created_at, "
    "review_candidates, is_duplicate, duplicate_of_anime_id"
)


def upgrade() -> None:
    """Upgrade schema.

    d85726b57997 already does this exact rebuild once, and tested repeatedly
    from an empty DB it verifiably drops the UNIQUE(anidb_id) constraint. A
    real-world report showed a database whose `alembic_version` recorded
    d85726b57997 as applied while the live table still enforced the
    constraint -- most likely two processes (a `cargo tauri dev` sidecar and
    a manually started `uvicorn`) migrating the same SQLite file at once.
    Unconditionally repeating the rebuild here (migrations only run once per
    database, so the extra I/O cost is a non-issue) heals that case; on an
    already-correct database this is a harmless no-op producing the same
    schema. Uses plain `op.execute()` throughout -- like every other
    migration -- rather than `op.get_bind().exec_driver_sql()` with PRAGMA
    introspection, which was observed to hang indefinitely specifically when
    run through the app's async startup path (`asyncio.to_thread` + Alembic's
    async/greenlet SQLite bridge), even though the equivalent plain-CLI
    `alembic upgrade head` run completed instantly.
    """
    op.execute(
        """
        CREATE TABLE anime_new (
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
            FOREIGN KEY(folder_id) REFERENCES folder (id),
            FOREIGN KEY(duplicate_of_anime_id) REFERENCES anime (id)
        )
        """
    )
    op.execute(f"INSERT INTO anime_new ({_COPY_COLUMNS}) SELECT {_COPY_COLUMNS} FROM anime")
    op.execute("DROP TABLE anime")
    op.execute("ALTER TABLE anime_new RENAME TO anime")
    op.execute("DROP INDEX IF EXISTS ix_anime_anidb_id")
    op.execute("CREATE INDEX ix_anime_anidb_id ON anime (anidb_id)")


def downgrade() -> None:
    """Downgrade schema."""
    pass  # d85726b57997's downgrade already restores the unique constraint
