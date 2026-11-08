"""Dependency requests (B3-9)

Revision ID: b30a00000027
Revises: b30a00000025
Create Date: 2026-11-02

Project-child table with the usual tenant_isolation policy (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a00000027"
down_revision: str | Sequence[str] | None = "b30a00000025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "dependency_requests",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("package", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("hashes", postgresql.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dependency_requests_project", "dependency_requests", ["project_id", "status"]
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dependency_requests")
    op.execute(
        f"CREATE POLICY tenant_isolation ON dependency_requests USING "
        f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dependency_requests")
    op.drop_index("ix_dependency_requests_project", table_name="dependency_requests")
    op.drop_table("dependency_requests")
