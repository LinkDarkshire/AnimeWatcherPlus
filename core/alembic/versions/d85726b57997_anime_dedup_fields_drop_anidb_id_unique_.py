"""anime dedup fields, drop anidb_id unique constraint

Revision ID: d85726b57997
Revises: d5464d886f44
Create Date: 2026-07-05 21:48:35.747373

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd85726b57997'
down_revision: Union[str, Sequence[str], None] = 'd5464d886f44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COPY_COLUMNS = (
    "id, folder_id, directory_path, anidb_id, title, original_title, alt_titles, "
    "year, media_type, description, poster_path, ident_status, match_score, "
    "episode_count_expected, missing_on_disk, last_metadata_refresh, created_at, "
    "review_candidates"
)


def upgrade() -> None:
    """Upgrade schema.

    Rebuilt with raw SQL rather than `batch_alter_table` (which reflects and
    silently carries forward the *existing* schema for anything it isn't
    told to change): the original `anidb_id` column has an unnamed inline
    UNIQUE constraint from its old `unique=True` definition, and Alembic's
    SQLite batch mode has no reliable way to detect/drop an anonymous
    constraint like that. FA-29 requires *detecting* the same AniDB ID
    reused across folders, not having the DB reject the second one.
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
    op.execute(
        f"INSERT INTO anime_new ({_COPY_COLUMNS}, is_duplicate, duplicate_of_anime_id) "
        f"SELECT {_COPY_COLUMNS}, 0, NULL FROM anime"
    )
    op.execute("DROP TABLE anime")
    op.execute("ALTER TABLE anime_new RENAME TO anime")
    op.execute("CREATE INDEX ix_anime_anidb_id ON anime (anidb_id)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_anime_anidb_id")
    op.execute(
        """
        CREATE TABLE anime_old (
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
            PRIMARY KEY (id),
            UNIQUE (directory_path),
            UNIQUE (anidb_id),
            FOREIGN KEY(folder_id) REFERENCES folder (id)
        )
        """
    )
    op.execute(f"INSERT INTO anime_old ({_COPY_COLUMNS}) SELECT {_COPY_COLUMNS} FROM anime")
    op.execute("DROP TABLE anime")
    op.execute("ALTER TABLE anime_old RENAME TO anime")
