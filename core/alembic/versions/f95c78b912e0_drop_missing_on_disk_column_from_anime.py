"""drop missing_on_disk column from anime

Revision ID: f95c78b912e0
Revises: 5535b539eb2b
Create Date: 2026-07-20 22:54:20.422262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f95c78b912e0'
down_revision: Union[str, Sequence[str], None] = '5535b539eb2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.drop_column('missing_on_disk')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('anime', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('missing_on_disk', sa.Boolean(), nullable=False, server_default=sa.false())
        )
