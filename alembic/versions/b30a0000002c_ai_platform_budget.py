"""Platform-wide AI spend counter (hard cap, CP-E)

Revision ID: b30a0000002c
Revises: b30a0000002b
Create Date: 2026-11-03

One global row, no RLS: it counts every real model call across all organizations, so the
platform cap cannot be dodged by switching organization.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a0000002c"
down_revision: str | Sequence[str] | None = "b30a0000002b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_platform_budget",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("spent_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cap_override_micro_usd", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_ai_platform_budget_singleton"),
    )
    op.execute("INSERT INTO ai_platform_budget (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("ai_platform_budget")
