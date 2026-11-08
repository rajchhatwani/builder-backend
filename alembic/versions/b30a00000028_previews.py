"""Preview runtime: previews, platform limits, per-org limits (B3-10)

Revision ID: b30a00000028
Revises: b30a00000027
Create Date: 2026-11-02

`previews` is a project-child table, `preview_org_limits` an org table (both get the usual
tenant_isolation policy; enabling RLS stays a separate step). The platform settings row is global.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a00000028"
down_revision: str | Sequence[str] | None = "b30a00000027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "previews",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("db_sandbox", sa.String(length=32), nullable=False),
        sa.Column("app_sandbox", sa.String(length=32), nullable=False),
        sa.Column("app_ip", sa.String(length=15), nullable=True),
        sa.Column("code_dir", sa.String(length=500), nullable=True),
        sa.Column("limits", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("wake_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_request_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_previews_project", "previews", ["project_id", "created_at"])
    op.create_index("ix_previews_owner_state", "previews", ["created_by", "state"])
    op.create_index("ix_previews_state_expiry", "previews", ["state", "expires_at"])
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON previews")
    op.execute(
        f"CREATE POLICY tenant_isolation ON previews USING "
        f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
    )

    op.create_table(
        "preview_platform_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kill_switch", sa.Boolean(), nullable=False),
        sa.Column("limits", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "preview_org_limits",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allow_above_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("limits", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON preview_org_limits")
    op.execute(
        f"CREATE POLICY tenant_isolation ON preview_org_limits USING "
        f"({_CTX} IS NULL OR organization_id = {_CTX}::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON preview_org_limits")
    op.drop_table("preview_org_limits")
    op.drop_table("preview_platform_settings")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON previews")
    op.drop_index("ix_previews_state_expiry", table_name="previews")
    op.drop_index("ix_previews_owner_state", table_name="previews")
    op.drop_index("ix_previews_project", table_name="previews")
    op.drop_table("previews")
