"""Phase A — Organizations core.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-26 14:00:00.000000

Adds organizations, organization_members, organization_invitations, plans, subscriptions.
Backfills:
  - every PlatformUser gets a personal Organization and becomes its owner on the 'free' plan;
  - every existing project is attached to its first owner's personal org (or an admin's one);
  - every existing audit row gets its organization_id stamp when the project is known.

The columns on projects.organization_id and platform_users.default_organization_id are
nullable at first so the backfill is single-pass and safe. New rows set them inside the
service layer, and later migrations (Phase F) will tighten to NOT NULL once we're sure
every row has one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str, length: int = 20) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("kind", _enum("org_kind", "personal", "team"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            _enum("org_role", "member", "admin", "owner"),
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )
    op.create_index(
        "ix_organization_members_user", "organization_members", ["user_id"]
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", _enum("org_role", "member", "admin", "owner"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["invited_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_organization_invitations_org", "organization_invitations", ["organization_id"]
    )
    op.create_index(
        "ix_organization_invitations_email", "organization_invitations", ["email"]
    )

    op.create_table(
        "plans",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("max_seats", sa.Integer(), nullable=True),
        sa.Column("max_projects", sa.Integer(), nullable=True),
        sa.Column("max_api_tokens", sa.Integer(), nullable=True),
        sa.Column("max_mcp_tokens", sa.Integer(), nullable=True),
        sa.Column("allow_sso", sa.Boolean(), nullable=False),
        sa.Column("allow_scim", sa.Boolean(), nullable=False),
        sa.Column("allow_mcp", sa.Boolean(), nullable=False),
        sa.Column("monthly_price_usd", sa.Integer(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.String(40), nullable=False),
        sa.Column(
            "status",
            _enum("subscription_status", "trial", "active", "past_due", "canceled"),
            nullable=False,
        ),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.String(64), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(64), nullable=True),
        sa.Column("seat_override", sa.Integer(), nullable=True),
        sa.Column("project_override", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("organization_id"),
    )

    # Extensions to existing tables ---------------------------------------------------
    op.add_column(
        "projects", sa.Column("organization_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_projects_organization",
        "projects",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_projects_org", "projects", ["organization_id"])

    op.add_column(
        "platform_audit_log", sa.Column("organization_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        "ix_platform_audit_org", "platform_audit_log", ["organization_id", "at"]
    )

    op.add_column(
        "platform_users",
        sa.Column("default_organization_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_platform_users_default_org",
        "platform_users",
        "organizations",
        ["default_organization_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Seed plans ----------------------------------------------------------------------
    plans = sa.table(
        "plans",
        sa.column("id", sa.String),
        sa.column("display_name", sa.String),
        sa.column("max_seats", sa.Integer),
        sa.column("max_projects", sa.Integer),
        sa.column("max_api_tokens", sa.Integer),
        sa.column("max_mcp_tokens", sa.Integer),
        sa.column("allow_sso", sa.Boolean),
        sa.column("allow_scim", sa.Boolean),
        sa.column("allow_mcp", sa.Boolean),
        sa.column("monthly_price_usd", sa.Integer),
        sa.column("is_public", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        plans.insert().values(
            [
                {
                    "id": "free",
                    "display_name": "Free",
                    "max_seats": 1,
                    "max_projects": 1,
                    "max_api_tokens": 3,
                    "max_mcp_tokens": 0,
                    "allow_sso": False,
                    "allow_scim": False,
                    "allow_mcp": False,
                    "monthly_price_usd": 0,
                    "is_public": True,
                    "created_at": sa.func.now(),
                },
                {
                    "id": "team",
                    "display_name": "Team",
                    "max_seats": 5,
                    "max_projects": 10,
                    "max_api_tokens": 20,
                    "max_mcp_tokens": 5,
                    "allow_sso": False,
                    "allow_scim": False,
                    "allow_mcp": True,
                    "monthly_price_usd": 2900,
                    "is_public": True,
                    "created_at": sa.func.now(),
                },
                {
                    "id": "business",
                    "display_name": "Business",
                    "max_seats": 25,
                    "max_projects": 50,
                    "max_api_tokens": 100,
                    "max_mcp_tokens": 25,
                    "allow_sso": True,
                    "allow_scim": False,
                    "allow_mcp": True,
                    "monthly_price_usd": 9900,
                    "is_public": True,
                    "created_at": sa.func.now(),
                },
                {
                    "id": "enterprise",
                    "display_name": "Enterprise",
                    "max_seats": None,
                    "max_projects": None,
                    "max_api_tokens": None,
                    "max_mcp_tokens": None,
                    "allow_sso": True,
                    "allow_scim": True,
                    "allow_mcp": True,
                    "monthly_price_usd": 0,  # custom, billed off-platform
                    "is_public": False,
                    "created_at": sa.func.now(),
                },
            ]
        )
    )

    # Backfill: a personal org for every existing user, make them its owner, and attach
    # their projects to it. Users without projects still get the personal org so that
    # /orgs always returns at least one row.
    op.execute(
        """
        INSERT INTO organizations (id, name, slug, kind, created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            COALESCE(NULLIF(name, ''), split_part(email, '@', 1)),
            lower(regexp_replace(
                split_part(email, '@', 1) || '-' ||
                substring(replace(id::text, '-', '') for 8),
                '[^a-z0-9]+', '-', 'g')),
            'personal',
            id,
            now(),
            now()
        FROM platform_users
        WHERE NOT EXISTS (
            SELECT 1 FROM organization_members om WHERE om.user_id = platform_users.id
        )
        """
    )
    op.execute(
        """
        INSERT INTO organization_members (organization_id, user_id, role, joined_at)
        SELECT o.id, o.created_by, 'owner', now()
        FROM organizations o
        WHERE o.kind = 'personal'
          AND o.created_by IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM organization_members om
              WHERE om.organization_id = o.id AND om.user_id = o.created_by
          )
        """
    )
    op.execute(
        """
        INSERT INTO subscriptions (
            organization_id, plan_id, status, updated_at
        )
        SELECT o.id, 'free', 'active', now()
        FROM organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM subscriptions s WHERE s.organization_id = o.id
        )
        """
    )
    op.execute(
        """
        UPDATE platform_users u
        SET default_organization_id = o.id
        FROM organizations o
        WHERE o.created_by = u.id
          AND o.kind = 'personal'
          AND u.default_organization_id IS NULL
        """
    )
    # Attach existing projects to their first owner's personal org.
    op.execute(
        """
        UPDATE projects p
        SET organization_id = sub.org_id
        FROM (
            SELECT pm.project_id, o.id AS org_id
            FROM project_members pm
            JOIN organizations o ON o.created_by = pm.user_id AND o.kind = 'personal'
            WHERE pm.role = 'owner'
        ) sub
        WHERE p.id = sub.project_id AND p.organization_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("UPDATE projects SET organization_id = NULL")
    op.execute("UPDATE platform_users SET default_organization_id = NULL")
    op.drop_constraint(
        "fk_platform_users_default_org", "platform_users", type_="foreignkey"
    )
    op.drop_column("platform_users", "default_organization_id")

    op.drop_index("ix_projects_org", table_name="projects")
    op.drop_constraint("fk_projects_organization", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")

    op.drop_index("ix_platform_audit_org", table_name="platform_audit_log")
    op.drop_column("platform_audit_log", "organization_id")

    op.drop_table("subscriptions")
    op.drop_table("plans")
    op.drop_index(
        "ix_organization_invitations_email", table_name="organization_invitations"
    )
    op.drop_index(
        "ix_organization_invitations_org", table_name="organization_invitations"
    )
    op.drop_table("organization_invitations")
    op.drop_index("ix_organization_members_user", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_table("organizations")
