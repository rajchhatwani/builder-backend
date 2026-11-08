"""SCIM 2.0 directory sync

Revision ID: a9c4e2f7b1d3
Revises: f5c3a8e1b7d9
Create Date: 2026-10-27

PLATFORM_SAAS_PLAN §3.1 `scim_directories`, §4.3, §12.E.1:
  - scim_directories: one per org, the bearer token's SHA-256 only, on/off, the group -> role
    dictionary (§12.E.3), last sync;
  - scim_users / scim_groups / scim_group_members: the resources the org's IdP manages. A SCIM
    user points at a Builder account; deactivating it removes the org membership, not the account.
"""

import sqlalchemy as sa

from alembic import op

revision = "a9c4e2f7b1d3"
down_revision = "f5c3a8e1b7d9"
branch_labels = None
depends_on = None


def _now() -> sa.sql.elements.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "scim_directories",
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bearer_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_hint", sa.String(12), nullable=False, server_default=""),
        sa.Column(
            "token_created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("group_roles", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_by",
            sa.UUID(),
            sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "scim_users",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("platform_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_name", sa.String(254), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("given_name", sa.String(100), nullable=True),
        sa.Column("family_name", sa.String(100), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index(
        "uq_scim_users_org_user", "scim_users", ["organization_id", "user_id"], unique=True
    )
    op.create_index(
        "uq_scim_users_org_user_name",
        "scim_users",
        ["organization_id", sa.text("lower(user_name)")],
        unique=True,
    )
    op.create_table(
        "scim_groups",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index(
        "uq_scim_groups_org_name",
        "scim_groups",
        ["organization_id", sa.text("lower(display_name)")],
        unique=True,
    )
    op.create_table(
        "scim_group_members",
        sa.Column(
            "group_id",
            sa.UUID(),
            sa.ForeignKey("scim_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "scim_user_id",
            sa.UUID(),
            sa.ForeignKey("scim_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_scim_group_members_user", "scim_group_members", ["scim_user_id"])


def downgrade() -> None:
    op.drop_index("ix_scim_group_members_user", table_name="scim_group_members")
    op.drop_table("scim_group_members")
    op.drop_index("uq_scim_groups_org_name", table_name="scim_groups")
    op.drop_table("scim_groups")
    op.drop_index("uq_scim_users_org_user_name", table_name="scim_users")
    op.drop_index("uq_scim_users_org_user", table_name="scim_users")
    op.drop_table("scim_users")
    op.drop_table("scim_directories")
