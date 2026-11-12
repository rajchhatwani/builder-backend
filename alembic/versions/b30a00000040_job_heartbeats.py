"""Operator job heartbeats (CP-5V)

Revision ID: b30a00000040
Revises: b30a0000003f
Create Date: 2026-11-13

One row per periodic job (reports, idle_sweep): last run, status, interval. Platform-level table,
no organization link (listed in the RLS allow-list test).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a00000040"
down_revision: str | Sequence[str] | None = "b30a0000003f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_heartbeats",
        sa.Column("job", sa.String(60), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status", sa.String(10), nullable=False),
        sa.Column("last_error", sa.String(120), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("runs", sa.BigInteger(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("job_heartbeats")
