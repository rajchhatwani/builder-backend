"""AI org settings (BYO key, budget) and the AI cost ledger

Revision ID: b30a00000023
Revises: b30a00000022
Create Date: 2026-11-02

Both tables carry organization_id; the tenant_isolation policy is installed like the other org
tables (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a00000023"
down_revision: str | Sequence[str] | None = "b30a00000022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("ai_org_settings", "ai_cost_ledger")


def upgrade() -> None:
    op.create_table(
        "ai_org_settings",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=True),
        sa.Column("api_key_hint", sa.String(length=8), nullable=True),
        sa.Column("monthly_budget_micro_usd", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_table(
        "ai_cost_ledger",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("task_class", sa.String(length=30), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_cost_ledger_org_created", "ai_cost_ledger", ["organization_id", "created_at"]
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR organization_id = {_CTX}::uuid)"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_ai_cost_ledger_org_created", table_name="ai_cost_ledger")
    op.drop_table("ai_cost_ledger")
    op.drop_table("ai_org_settings")
