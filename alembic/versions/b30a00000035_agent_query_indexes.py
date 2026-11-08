"""Indexes for the approvals inbox and the workspace-busy guard

Revision ID: b30a00000035
Revises: b30a00000034
Create Date: 2026-11-08

S1-014: the inbox filters ai_approvals by (project_id, state) ordered by created_at; the workspace
busy check filters ai_runs by (workspace_id, state).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b30a00000035"
down_revision: str | Sequence[str] | None = "b30a00000034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_approvals_project_state", "ai_approvals", ["project_id", "state", "created_at"]
    )
    op.create_index("ix_ai_runs_workspace_state", "ai_runs", ["workspace_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_ai_runs_workspace_state", table_name="ai_runs")
    op.drop_index("ix_ai_approvals_project_state", table_name="ai_approvals")
