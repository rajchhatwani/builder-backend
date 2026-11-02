"""Registry: block versions, hooks ledger, dependency lock (per project)

Revision ID: b30a00000024
Revises: b30a00000023
Create Date: 2026-11-02

Project-child tables with the usual tenant_isolation policy (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a00000024"
down_revision: str | Sequence[str] | None = "b30a00000023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("registry_block_versions", "registry_hooks_ledger", "registry_deps_lock")


def _project_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "registry_block_versions",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        _project_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", "version", name="uq_registry_block"),
    )
    op.create_table(
        "registry_hooks_ledger",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("hook_name", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        _project_fk(),
        sa.ForeignKeyConstraint(["approved_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "hook_name", "content_hash", name="uq_registry_hook"),
    )
    op.create_index(
        "ix_registry_hooks_project", "registry_hooks_ledger", ["project_id", "hook_name"]
    )
    op.create_table(
        "registry_deps_lock",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("package", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("hash", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        _project_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "package", "version", name="uq_registry_dep"),
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
    op.drop_table("registry_deps_lock")
    op.drop_index("ix_registry_hooks_project", table_name="registry_hooks_ledger")
    op.drop_table("registry_hooks_ledger")
    op.drop_table("registry_block_versions")
