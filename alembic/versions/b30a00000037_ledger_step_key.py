"""Ledger step key (B-009)

Revision ID: b30a00000037
Revises: b30a00000036
Create Date: 2026-11-09

ai_cost_ledger.step_key ("run_id:seq") with a partial unique index: a retried agent step never
writes a second ledger row. Existing rows keep NULL (the index ignores them).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b30a00000037"
down_revision: str | Sequence[str] | None = "b30a00000036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_cost_ledger", sa.Column("step_key", sa.String(120), nullable=True))
    op.create_index(
        "uq_ai_cost_ledger_step_key",
        "ai_cost_ledger",
        ["step_key"],
        unique=True,
        postgresql_where=sa.text("step_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_cost_ledger_step_key", table_name="ai_cost_ledger")
    op.drop_column("ai_cost_ledger", "step_key")
