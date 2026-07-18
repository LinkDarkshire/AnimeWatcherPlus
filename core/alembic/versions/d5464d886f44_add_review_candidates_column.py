"""add review candidates column

Revision ID: d5464d886f44
Revises: 1fa66dc87076
Create Date: 2026-07-04 16:17:27.666243

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5464d886f44'
down_revision: Union[str, Sequence[str], None] = '1fa66dc87076'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Note: FTS5 shadow tables (anime_search_fts*, anidb_title_fts*) are not part
    # of the SQLAlchemy metadata and were dropped by --autogenerate as false
    # positives; that noise has been removed from this migration by hand.
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_candidates', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.drop_column('review_candidates')
