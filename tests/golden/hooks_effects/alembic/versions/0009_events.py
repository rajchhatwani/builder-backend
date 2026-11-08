"""events outbox

Revision ID: 0009
Revises: 0002
Create Date: rendered from the spec by Backend Builder

The transactional outbox (events written with the change that caused them) and the consumer ledger.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ev_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ev_outbox"),
        sa.UniqueConstraint("aggregate_type", "aggregate_id", "seq", name="uq_ev_outbox_aggregate_seq"),
    )
    op.create_index("ix_ev_outbox_claim", "ev_outbox", ["status", "next_attempt_at"])
    op.create_index("ix_ev_outbox_delivered_at", "ev_outbox", ["delivered_at"])
    op.create_table(
        "ev_handled",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(200), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "consumer", name="pk_ev_handled"),
    )
    op.create_index("ix_ev_handled_handled_at", "ev_handled", ["handled_at"])


def downgrade() -> None:
    op.drop_index("ix_ev_handled_handled_at", table_name="ev_handled")
    op.drop_table("ev_handled")
    op.drop_index("ix_ev_outbox_delivered_at", table_name="ev_outbox")
    op.drop_index("ix_ev_outbox_claim", table_name="ev_outbox")
    op.drop_table("ev_outbox")
