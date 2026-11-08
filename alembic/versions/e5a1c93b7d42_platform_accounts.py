"""platform accounts, sessions, api tokens, project members, audit log

Revision ID: e5a1c93b7d42
Revises: d4f8b6c21a73
Create Date: 2026-10-24 15:00:00.000000

Existing projects get no member rows: they are "unclaimed" and invisible to customers until the
bootstrap administrator is created, which adopts them as owner (see platform_auth_service).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a1c93b7d42"
down_revision: str | Sequence[str] | None = "d4f8b6c21a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str, length: int = 20) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def upgrade() -> None:
    op.create_table(
        "platform_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("status", _enum("account_status", "active", "suspended"), nullable=False),
        sa.Column(
            "platform_role",
            _enum("platform_role", "customer", "platform_support", "platform_admin"),
            nullable=False,
        ),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint("email = lower(email)", name="ck_platform_users_email_lower"),
    )

    op.create_table(
        "platform_refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("audience", _enum("token_audience", "app", "admin", length=10), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_platform_refresh_family", "platform_refresh_tokens", ["family_id"])

    op.create_table(
        "platform_api_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("public_id", sa.String(10), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )

    op.create_table(
        "project_members",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role", _enum("member_role", "viewer", "editor", "owner", length=10), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_index("ix_project_members_user", "project_members", ["user_id"])

    op.create_table(
        "platform_audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_email", sa.String(254), nullable=True),
        sa.Column("via", sa.String(10), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "result", _enum("audit_result", "ok", "denied", "error", length=10), nullable=False
        ),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_audit_at", "platform_audit_log", ["at"])
    op.create_index("ix_platform_audit_actor", "platform_audit_log", ["actor_id", "at"])
    op.create_index("ix_platform_audit_project", "platform_audit_log", ["project_id", "at"])

    # Append-only: a compromised application role cannot quietly rewrite history through the ORM.
    # (A database superuser still can; ship the log elsewhere for real tamper evidence.)
    op.execute(
        """
        CREATE FUNCTION platform_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'platform_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_audit_log_no_change
        BEFORE UPDATE OR DELETE ON platform_audit_log
        FOR EACH ROW EXECUTE FUNCTION platform_audit_log_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS platform_audit_log_no_change ON platform_audit_log")
    op.execute("DROP FUNCTION IF EXISTS platform_audit_log_immutable()")
    op.drop_table("platform_audit_log")
    op.drop_table("project_members")
    op.drop_table("platform_api_tokens")
    op.drop_table("platform_refresh_tokens")
    op.drop_table("platform_users")
