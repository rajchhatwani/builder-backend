"""Shared rate-limit windows

Revision ID: b30a00000036
Revises: b30a00000035
Create Date: 2026-11-08

FX-1 / S2-005 / S2-011b: preview proxy and intake counters move from per-process dicts to a small
fixed-window table so N workers cannot allow N times the limit. Platform infrastructure: no
organization column, deliberately outside the RLS list.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b30a00000036"
down_revision: str | Sequence[str] | None = "b30a00000035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_windows",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("window_start", sa.BigInteger, primary_key=True),
        sa.Column("hits", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_rate_windows_expires", "rate_windows", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_windows_expires", table_name="rate_windows")
    op.drop_table("rate_windows")
