"""spec op-log

Revision ID: a7c3e9d1f4b6
Revises: b4e7c1a9d352
Create Date: 2026-11-01

Adds spec_ops (append-only log of typed spec operations per project) and its tenant_isolation
policy, installed like the other project-child tables (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c3e9d1f4b6"
down_revision: str | Sequence[str] | None = "b4e7c1a9d352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "spec_ops",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("actor_kind", sa.String(length=10), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("op_type", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("ref_seq", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inverse", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spec_hash_before", sa.String(length=64), nullable=False),
        sa.Column("spec_hash_after", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "seq", name="uq_spec_ops_project_seq"),
    )
    op.create_index("ix_spec_ops_project_seq", "spec_ops", ["project_id", "seq"])
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON spec_ops")
    op.execute(
        "CREATE POLICY tenant_isolation ON spec_ops USING "
        f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON spec_ops")
    op.drop_index("ix_spec_ops_project_seq", table_name="spec_ops")
    op.drop_table("spec_ops")
