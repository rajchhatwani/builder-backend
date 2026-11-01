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
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("email", sa.String(120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("email", name="uq_customers_email"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_no", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("memo", sa.String(200), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        sa.UniqueConstraint("invoice_no", name="uq_invoices_invoice_no"),
    )
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_foreign_key(
        "fk_invoices_customer_id_customers",
        "invoices",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_invoices_customer_id_customers", "invoices", type_="foreignkey")
    op.drop_table("invoices")
    op.drop_table("customers")
