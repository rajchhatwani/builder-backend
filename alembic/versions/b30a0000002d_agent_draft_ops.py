"""Agent draft spec operations (H2)

Revision ID: b30a0000002d
Revises: b30a0000002c
Create Date: 2026-11-03

A run edits a private draft of the spec; these rows are the draft. Project-child table with the
usual tenant_isolation policy (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a0000002d"
down_revision: str | Sequence[str] | None = "b30a0000002c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "ai_draft_ops",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("op_type", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["ai_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_ai_draft_ops_run_seq", "ai_draft_ops", ["run_id", "seq"], unique=True)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_draft_ops")
    op.execute(
        f"CREATE POLICY tenant_isolation ON ai_draft_ops USING "
        f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_draft_ops")
    op.drop_index("uq_ai_draft_ops_run_seq", table_name="ai_draft_ops")
    op.drop_table("ai_draft_ops")
