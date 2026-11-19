"""ai pack: gateway cost ledger and budget periods

Revision ID: 0038
Revises: 0009
Create Date: rendered from the spec by Backend Builder

ai_calls is the cost ledger (one row per call, also the failed ones); ai_budget_periods holds the spent and reserved
micro-USD of a period and is the row a call locks while it reserves or settles. An idempotency key is unique per
caller among calls that did not end in `error`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("caller_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="reserved", nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cost_micro_usd >= 0 AND reserved_micro_usd >= 0", name="ck_ai_calls_amounts"),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_ai_calls_tokens"),
        sa.CheckConstraint("status IN ('reserved', 'ok', 'error')", name="ck_ai_calls_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_ai_calls_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_calls_tenant_id"), "ai_calls", ["tenant_id"], unique=False)
    op.create_index("ix_ai_calls_period_start_status", "ai_calls", ["period_start", "status"], unique=False)
    op.create_index("ix_ai_calls_created_at", "ai_calls", ["created_at"], unique=False)
    op.create_index(
        "uq_ai_calls_idempotency_key",
        "ai_calls",
        ["tenant_id", "caller_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL AND status <> 'error'"),
    )

    op.create_table(
        "ai_budget_periods",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("spent_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("spent_micro_usd >= 0 AND reserved_micro_usd >= 0", name="ck_ai_budget_periods_amounts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_ai_budget_periods_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "period_start", name="uq_ai_budget_periods_period"),
    )
    op.create_index(op.f("ix_ai_budget_periods_tenant_id"), "ai_budget_periods", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("ai_budget_periods")
    op.drop_table("ai_calls")
