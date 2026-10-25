"""download_request: when it finished, which download folder it went to

Revision ID: b7e2c4d9a1f3
Revises: a1d4e7b2c9f0
Create Date: 2026-10-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c4d9a1f3"
down_revision: str | Sequence[str] | None = "a1d4e7b2c9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("download_request") as batch:
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("folder_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("download_request") as batch:
        batch.drop_column("folder_id")
        batch.drop_column("finished_at")
