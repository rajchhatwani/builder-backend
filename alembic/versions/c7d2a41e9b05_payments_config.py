"""payments config

Revision ID: c7d2a41e9b05
Revises: b3e1f7a92c64
Create Date: 2026-10-23 20:00:00.000000

Adds the project_payments_configs table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c7d2a41e9b05"
down_revision: str | Sequence[str] | None = "b3e1f7a92c64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_payments_configs",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("stripe", "razorpay", name="payment_provider", native_enum=False, length=12),
            nullable=False,
        ),
        sa.Column("payable", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("currencies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("success_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cancel_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("refund_approval_threshold_minor", sa.BigInteger(), nullable=True),
        sa.Column("scale", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("security", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_payments_configs")
