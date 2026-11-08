"""runtime config

Revision ID: 0006
Revises: 0005
Create Date: rendered from the spec by Backend Builder

Setting values, sequence counters and list items.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rc_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "key", name="pk_rc_settings"),
    )
    op.create_table(
        "rc_sequences",
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("next_value", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("name", "tenant_id", "period", name="pk_rc_sequences"),
    )
    op.create_table(
        "rc_list_items",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("list_name", sa.String(60), nullable=False),
        sa.Column("value", sa.String(40), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "list_name", "value", name="pk_rc_list_items"),
    )


def downgrade() -> None:
    op.drop_table("rc_list_items")
    op.drop_table("rc_sequences")
    op.drop_table("rc_settings")
