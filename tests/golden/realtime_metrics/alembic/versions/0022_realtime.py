"""realtime event log

Revision ID: 0022
Revises: 0005
Create Date: rendered from the spec by Backend Builder

The realtime event log (ids only, never field values) and the prune floor.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rt_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity", sa.String(80), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rt_events"),
    )
    op.create_index("ix_rt_events_created_at", "rt_events", ["created_at"])
    op.create_table(
        "rt_floor",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("floor_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rt_floor"),
    )


def downgrade() -> None:
    op.drop_table("rt_floor")
    op.drop_index("ix_rt_events_created_at", table_name="rt_events")
    op.drop_table("rt_events")
