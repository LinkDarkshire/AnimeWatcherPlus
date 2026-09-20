"""add title variant columns to anime

Revision ID: a3c1d7e04b19
Revises: f95c78b912e0
Create Date: 2026-09-14 10:12:03.118427

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c1d7e04b19'
down_revision: Union[str, Sequence[str], None] = 'f95c78b912e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Nullable on purpose: existing rows keep NULL variants until a rescan or
    the aniinfo.json backfill (services.titles.resync_titles) fills them, and
    title resolution falls back to the already-stored `title` meanwhile.
    """
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.add_column(sa.Column('title_main', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('title_en', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('title_ja', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.drop_column('title_ja')
        batch_op.drop_column('title_en')
        batch_op.drop_column('title_main')
