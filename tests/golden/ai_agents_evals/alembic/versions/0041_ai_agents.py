"""ai pack: agent runtime tables

Revision ID: 0041
Revises: 0038
Create Date: rendered from the spec by Backend Builder

ai_agent_runs holds one agent run (goal, mode, status, link to the gateway ledger call); ai_agent_proposals one proposed
action with the status the autonomy dial gave it. `eval` flags the dry runs of the eval harness (hidden from the inbox).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("effective_autonomy", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="completed", nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.Column("eval", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('completed', 'failed', 'refused')", name="ck_ai_agent_runs_status"),
        sa.CheckConstraint("mode IN ('suggest', 'draft', 'auto')", name="ck_ai_agent_runs_mode"),
        sa.CheckConstraint("effective_autonomy IN ('suggest', 'draft', 'auto')", name="ck_ai_agent_runs_effective_autonomy"),
        sa.ForeignKeyConstraint(["call_id"], ["ai_calls.id"], name="fk_ai_agent_runs_call_id_ai_calls", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_ai_agent_runs_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_agent_runs_tenant_id"), "ai_agent_runs", ["tenant_id"], unique=False)
    op.create_index("ix_ai_agent_runs_agent_created_at", "ai_agent_runs", ["agent", "created_at"], unique=False)
    op.create_index(
        "uq_ai_agent_runs_idempotency_key",
        "ai_agent_runs",
        ["tenant_id", "started_by", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "ai_agent_proposals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("risk", sa.String(length=8), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("allowed_autonomy", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("executed_by", sa.String(length=40), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("handoff_role", sa.String(length=40), nullable=True),
        sa.Column("outcome", sa.String(length=8), nullable=True),
        sa.Column("outcome_by", sa.Uuid(), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eval", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('suggested', 'acknowledged', 'pending_approval', 'executed', 'failed', 'rejected', 'rejected_by_policy', 'handed_off')",
            name="ck_ai_agent_proposals_status",
        ),
        sa.CheckConstraint("allowed_autonomy IN ('suggest', 'draft', 'auto')", name="ck_ai_agent_proposals_allowed_autonomy"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('success', 'failure', 'neutral')", name="ck_ai_agent_proposals_outcome"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_agent_runs.id"], name="fk_ai_agent_proposals_run_id_ai_agent_runs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_ai_agent_proposals_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_agent_proposals_run_id"), "ai_agent_proposals", ["run_id"], unique=False)
    op.create_index(op.f("ix_ai_agent_proposals_tenant_id"), "ai_agent_proposals", ["tenant_id"], unique=False)
    op.create_index("ix_ai_agent_proposals_status_created_at", "ai_agent_proposals", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("ai_agent_proposals")
    op.drop_table("ai_agent_runs")
