"""project behavior (state machines)

Revision ID: b4e7c1a9d352
Revises: a3d9c1e7b5f4
Create Date: 2026-11-01

Adds project_behavior (declarative behaviour of a project, one JSONB section per block) and its
tenant_isolation policy (installed like the others; enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b4e7c1a9d352"
down_revision: str | Sequence[str] | None = "a3d9c1e7b5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "project_behavior",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON project_behavior")
    op.execute(
        "CREATE POLICY tenant_isolation ON project_behavior USING "
        f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON project_behavior")
    op.drop_table("project_behavior")
