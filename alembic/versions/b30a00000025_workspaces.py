"""Draft workspaces and checkpoints (B3-4)

Revision ID: b30a00000025
Revises: b30a00000024
Create Date: 2026-11-02

Project-child tables with the usual tenant_isolation policy (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a00000025"
down_revision: str | Sequence[str] | None = "b30a00000024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("workspaces", "workspace_checkpoints")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("base_spec_seq", sa.Integer(), nullable=False),
        sa.Column("spec_seq", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(length=100), nullable=False),
        sa.Column("worktree_path", sa.String(length=500), nullable=True),
        sa.Column("preview_db_name", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_project", "workspaces", ["project_id", "created_at"])
    op.create_table(
        "workspace_checkpoints",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=False),
        sa.Column("git_tag", sa.String(length=100), nullable=False),
        sa.Column("spec_seq", sa.Integer(), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("db_snapshot", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ws_checkpoints_ws", "workspace_checkpoints", ["workspace_id", "created_at"]
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_ws_checkpoints_ws", table_name="workspace_checkpoints")
    op.drop_table("workspace_checkpoints")
    op.drop_index("ix_workspaces_project", table_name="workspaces")
    op.drop_table("workspaces")
