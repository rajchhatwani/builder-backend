"""Run-wide wall-clock counter on ai_runs

Revision ID: b30a00000033
Revises: b30a00000032
Create Date: 2026-11-08

B-008/S1-009: the wall budget was measured per drive() call. The active driving time is now
persisted on the run row (steps_used already was), so approvals and crash resumes cannot reset it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a00000033"
down_revision: str | Sequence[str] | None = "b30a00000032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_runs", sa.Column("wall_ms_used", sa.BigInteger(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("ai_runs", "wall_ms_used")
