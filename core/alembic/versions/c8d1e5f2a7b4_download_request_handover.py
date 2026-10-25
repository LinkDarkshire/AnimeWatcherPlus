"""download_request: handover to the client (pending while a link is resolved)

Revision ID: c8d1e5f2a7b4
Revises: b7e2c4d9a1f3
Create Date: 2026-10-26

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d1e5f2a7b4"
down_revision: str | Sequence[str] | None = "b7e2c4d9a1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("download_request") as batch:
        batch.add_column(sa.Column("handover", sa.String(), nullable=False, server_default="sent"))
        batch.add_column(sa.Column("handover_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("download_request") as batch:
        batch.drop_column("handover_error")
        batch.drop_column("handover")
