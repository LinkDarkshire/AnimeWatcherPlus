"""add indexes for large libraries

Revision ID: b7e2f4a91c63
Revises: a3c1d7e04b19
Create Date: 2026-09-14 12:41:55.702318

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e2f4a91c63'
down_revision: Union[str, Sequence[str], None] = 'a3c1d7e04b19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index name, table, column). Every one of these backs a query that runs
# per-anime or per-page, so on a large library their absence turns into a full
# table scan each time:
#   local_episode.anime_id   -- the scan loop's per-anime episode lookup
#   expected_episode.anime_id-- episode matching for the sort/rename queues
#   anime.folder_id          -- "everything under this folder" during a scan
#   anime.title              -- the library grid's ORDER BY, now paginated
#   anime.ident_status       -- the queue filters
#   anime_tag.tag_id         -- the library's tag filter join
#   anime_provider_id/job_log.anime_id -- the per-anime cascade deletes
_INDEXES = [
    ("ix_local_episode_anime_id", "local_episode", "anime_id"),
    ("ix_expected_episode_anime_id", "expected_episode", "anime_id"),
    ("ix_anime_folder_id", "anime", "folder_id"),
    ("ix_anime_title", "anime", "title"),
    ("ix_anime_ident_status", "anime", "ident_status"),
    ("ix_anime_tag_tag_id", "anime_tag", "tag_id"),
    ("ix_anime_provider_id_anime_id", "anime_provider_id", "anime_id"),
    ("ix_job_log_anime_id", "job_log", "anime_id"),
]


def upgrade() -> None:
    """Upgrade schema.

    Skips tables that aren't present. A healthy DB reaching this revision has
    all of them (they come from the initial schema), but this chain is also
    entered from hand-repaired/partial SQLite files -- see 280262530db1, which
    exists because a real library.db was found with its recorded revision out
    of step with its actual schema. A purely additive index migration must not
    be what finally hard-fails such a DB.
    """
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name, table_name, column_name in _INDEXES:
        if table_name in existing:
            op.create_index(name, table_name, [column_name])


def downgrade() -> None:
    """Downgrade schema."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name, table_name, _ in reversed(_INDEXES):
        if table_name in existing:
            op.drop_index(name, table_name=table_name)
