"""add wishlist_entry table

Revision ID: c4d8e2f1a7b3
Revises: b7e2f4a91c63
Create Date: 2026-10-10 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d8e2f1a7b3'
down_revision: str | Sequence[str] | None = 'b7e2f4a91c63'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'wishlist_entry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('anidb_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('media_type', sa.String(), nullable=True),
        sa.Column('episode_count', sa.Integer(), nullable=True),
        sa.Column('details_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('anidb_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('wishlist_entry')
