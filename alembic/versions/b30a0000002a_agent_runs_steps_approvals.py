"""Builder agent runs, steps and approvals (B3-1, B3-5)

Revision ID: b30a0000002a
Revises: b30a00000029
Create Date: 2026-11-02

Project-child tables with the usual tenant_isolation policy (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a0000002a"
down_revision: str | Sequence[str] | None = "b30a00000029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("ai_runs", "ai_steps", "ai_approvals")


def _pk_project() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        *_pk_project(),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("phase", sa.String(length=10), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("plan_hash", sa.String(length=64), nullable=True),
        sa.Column("budgets", postgresql.JSONB(), nullable=False),
        sa.Column("steps_used", sa.Integer(), nullable=False),
        sa.Column("repairs_used", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("stop_code", sa.String(length=40), nullable=True),
        sa.Column("stop_detail", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_runs_project", "ai_runs", ["project_id", "created_at"])
    op.create_table(
        "ai_steps",
        *_pk_project(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("tool_name", sa.String(length=60), nullable=True),
        sa.Column("tool_call_id", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("model", sa.String(length=60), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("tool_set_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_ai_steps_run_seq", "ai_steps", ["run_id", "seq"], unique=True)
    op.create_index(
        "uq_ai_steps_run_call",
        "ai_steps",
        ["run_id", "tool_call_id"],
        unique=True,
        postgresql_where=sa.text("tool_call_id IS NOT NULL"),
    )
    op.create_table(
        "ai_approvals",
        *_pk_project(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=1), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("risk_flags", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("bound_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("bound_commit", sa.String(length=40), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_approvals_run", "ai_approvals", ["run_id", "created_at"])
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_ai_approvals_run", table_name="ai_approvals")
    op.drop_table("ai_approvals")
    op.drop_index("uq_ai_steps_run_call", table_name="ai_steps")
    op.drop_index("uq_ai_steps_run_seq", table_name="ai_steps")
    op.drop_table("ai_steps")
    op.drop_index("ix_ai_runs_project", table_name="ai_runs")
    op.drop_table("ai_runs")
