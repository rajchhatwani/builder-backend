"""seed data

Revision ID: 0008
Revises: 0006
Create Date: rendered from the spec by Backend Builder

Which rows the seed created, so that `python -m app.seed --reset` removes only those.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seed_rows",
        sa.Column("table_name", sa.String(80), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("profile", sa.String(24), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("table_name", "record_id", name="pk_seed_rows"),
    )


def downgrade() -> None:
    op.drop_table("seed_rows")
