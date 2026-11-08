"""Expiring spend reservations (platform cap + org budget)

Revision ID: b30a0000002f
Revises: b30a0000002d
Create Date: 2026-11-08

S2-007/S1-007: reservations carry an expiry so a crash between reserve and settle cannot shrink
the cap for good. S2-009: org budget reservations live in the same table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a0000002f"
down_revision: str | Sequence[str] | None = "b30a0000002d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_spend_reservations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_spend_reservations_expires", "ai_spend_reservations", ["expires_at"])
    op.create_index("ix_ai_spend_reservations_org", "ai_spend_reservations", ["organization_id"])
    # Reservations made before this migration have no row to expire: start the counter clean.
    op.execute("UPDATE ai_platform_budget SET reserved_micro_usd = 0")


def downgrade() -> None:
    op.drop_index("ix_ai_spend_reservations_org", table_name="ai_spend_reservations")
    op.drop_index("ix_ai_spend_reservations_expires", table_name="ai_spend_reservations")
    op.drop_table("ai_spend_reservations")
