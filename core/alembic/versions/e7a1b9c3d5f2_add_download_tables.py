"""add download_integration and download_request tables

Revision ID: e7a1b9c3d5f2
Revises: c4d8e2f1a7b3
Create Date: 2026-10-10 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7a1b9c3d5f2'
down_revision: str | Sequence[str] | None = 'c4d8e2f1a7b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'download_integration',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plugin_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'download_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('anime_id', sa.Integer(), nullable=True),
        sa.Column('wishlist_entry_id', sa.Integer(), nullable=True),
        sa.Column('episode', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('link', sa.Text(), nullable=False),
        sa.Column('client_name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_download_request_anime_id', 'download_request', ['anime_id'])
    op.create_index('ix_download_request_wishlist_entry_id', 'download_request', ['wishlist_entry_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_download_request_wishlist_entry_id', table_name='download_request')
    op.drop_index('ix_download_request_anime_id', table_name='download_request')
    op.drop_table('download_request')
    op.drop_table('download_integration')
