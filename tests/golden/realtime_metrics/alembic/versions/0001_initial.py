"""initial schema

Revision ID: 0001
Revises:
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("rate", sa.Float(), nullable=True),
        sa.Column("paid", sa.Boolean(), nullable=True),
        sa.Column("cost_basis", sa.Numeric(18, 6), nullable=True),
        sa.Column("spent_on", sa.Date(), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code", sa.String(20), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_expenses"),
    )
    op.create_table(
        "payrolls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person", sa.String(80), nullable=False),
        sa.Column("salary", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_payrolls"),
    )


def downgrade() -> None:
    op.drop_table("payrolls")
    op.drop_table("expenses")
