"""download_request: client id, external id, dismissed

Revision ID: f3c9d2a8b4e6
Revises: e7a1b9c3d5f2
Create Date: 2026-10-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3c9d2a8b4e6'
down_revision: str | Sequence[str] | None = 'e7a1b9c3d5f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('download_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_integration_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('external_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('dismissed', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('download_request', schema=None) as batch_op:
        batch_op.drop_column('dismissed')
        batch_op.drop_column('external_id')
        batch_op.drop_column('client_integration_id')
