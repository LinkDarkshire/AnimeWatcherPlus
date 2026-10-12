"""add no_scan column to anime

Revision ID: 5535b539eb2b
Revises: 280262530db1
Create Date: 2026-07-20 21:36:36.098773

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5535b539eb2b'
down_revision: Union[str, Sequence[str], None] = '280262530db1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('no_scan', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.drop_column('no_scan')
