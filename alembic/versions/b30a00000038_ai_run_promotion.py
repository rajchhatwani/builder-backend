"""Pending promotion of agent-written custom code (FX-3 / B-004)

Revision ID: b30a00000038
Revises: b30a00000037
Create Date: 2026-11-09

ai_runs.promotion holds the custom-zone files an approved run still has to commit to main. It is
written in the same transaction as the spec apply, so a crash before the commit can be retried by
the sweeper instead of leaving the spec live without its code. ai_runs.paused_at (G3) is the pause
flag of a live run: the driver stops at its next step and the sweeper leaves the run alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b30a00000038"
down_revision: str | Sequence[str] | None = "b30a00000037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_runs", sa.Column("promotion", postgresql.JSONB(), nullable=True))
    op.add_column("ai_runs", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_runs", "paused_at")
    op.drop_column("ai_runs", "promotion")
