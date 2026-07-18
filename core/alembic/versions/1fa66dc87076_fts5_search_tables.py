"""fts5 search tables

Revision ID: 1fa66dc87076
Revises: f51e751d9c84
Create Date: 2026-07-04 16:02:09.842386

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1fa66dc87076'
down_revision: Union[str, Sequence[str], None] = 'f51e751d9c84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Content-linked FTS5 index over the AniDB title dump (single plain-text column,
    # safe to sync via triggers). The dump is wholesale-replaced on import, never
    # updated in place, so only INSERT/DELETE triggers are needed.
    op.execute(
        "CREATE VIRTUAL TABLE anidb_title_fts USING fts5("
        "title, content='anidb_title_index', content_rowid='id')"
    )
    op.execute(
        "CREATE TRIGGER anidb_title_ai AFTER INSERT ON anidb_title_index BEGIN "
        "INSERT INTO anidb_title_fts(rowid, title) VALUES (new.id, new.title); END"
    )
    op.execute(
        "CREATE TRIGGER anidb_title_ad AFTER DELETE ON anidb_title_index BEGIN "
        "INSERT INTO anidb_title_fts(anidb_title_fts, rowid, title) "
        "VALUES ('delete', old.id, old.title); END"
    )

    # Plain (non content-linked) FTS5 table for the anime library, since alt_titles
    # is a JSON column and not directly triggerable as flat text. AnimeRepo keeps
    # this table in sync explicitly (delete+insert per anime_id) on write.
    op.execute(
        "CREATE VIRTUAL TABLE anime_search_fts USING fts5("
        "anime_id UNINDEXED, title, alt_titles_text)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS anime_search_fts")
    op.execute("DROP TRIGGER IF EXISTS anidb_title_ad")
    op.execute("DROP TRIGGER IF EXISTS anidb_title_ai")
    op.execute("DROP TABLE IF EXISTS anidb_title_fts")
