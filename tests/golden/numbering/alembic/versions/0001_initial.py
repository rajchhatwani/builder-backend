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
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer", sa.String(120), nullable=False),
        sa.Column("total", sa.Numeric(18, 6), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("invoice_no", sa.String(40), nullable=False),
        sa.Column("order_no", sa.String(40), nullable=False),
        sa.Column("ticket_no", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("invoice_no", name="uq_orders_invoice_no"),
        sa.UniqueConstraint("order_no", name="uq_orders_order_no"),
        sa.UniqueConstraint("ticket_no", name="uq_orders_ticket_no"),
    )


def downgrade() -> None:
    op.drop_table("orders")
