"""auth config tables

Revision ID: aa9d78f96e73
Revises: 7c1d9a3e5b20
Create Date: 2026-10-23 01:21:00.000000

Adds four new tables for Phase 2 auth system:
  - project_auth_configs  (1:1 with projects)
  - project_roles         (many per project)
  - project_permissions   (many per project)
  - auth_custom_fields    (many per project)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa9d78f96e73"
down_revision: str | Sequence[str] | None = "7c1d9a3e5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    # ── project_auth_configs ──────────────────────────────────────────────────
    op.create_table(
        "project_auth_configs",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "token_store",
            sa.Enum("db", "redis", name="token_store", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("access_token_ttl_minutes", sa.Integer(), nullable=False),
        sa.Column("refresh_token_ttl_days", sa.Integer(), nullable=False),
        sa.Column(
            "jwt_algorithm",
            sa.Enum("HS256", "RS256", name="jwt_algorithm", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("email_magic_link_enabled", sa.Boolean(), nullable=False),
        sa.Column("sms_otp_enabled", sa.Boolean(), nullable=False),
        sa.Column("otp_ttl_minutes", sa.Integer(), nullable=False),
        sa.Column("email_verification_required", sa.Boolean(), nullable=False),
        sa.Column(
            "deletion_mode",
            sa.Enum("soft", "hard", name="deletion_mode", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("invite_only", sa.Boolean(), nullable=False),
        sa.Column("multi_tenant", sa.Boolean(), nullable=False),
        sa.Column(
            "smtp_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "sms_provider",
            sa.Enum(
                "twilio",
                "aws_sns",
                "vonage",
                name="sms_provider",
                native_enum=False,
                length=15,
            ),
            nullable=True,
        ),
        sa.Column(
            "sms_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("login_rate_limit", sa.String(length=50), nullable=False),
        sa.Column("register_rate_limit", sa.String(length=50), nullable=False),
        sa.Column("reset_rate_limit", sa.String(length=50), nullable=False),
        sa.Column("security_headers_enabled", sa.Boolean(), nullable=False),
        sa.Column("app_name", sa.String(length=100), nullable=True),
        sa.Column("app_url", sa.Text(), nullable=True),
        sa.Column(
            "email_templates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),  # enforces 1:1 relationship
    )

    # ── project_roles ─────────────────────────────────────────────────────────
    op.create_table(
        "project_roles",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("self_assignable", sa.Boolean(), nullable=False),
        sa.Column("invite_only", sa.Boolean(), nullable=False),
        sa.Column("inherits_from", sa.String(length=60), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_roles_project_name"),
    )
    op.create_index(
        "ix_project_roles_project_id",
        "project_roles",
        ["project_id"],
    )

    # ── project_permissions ───────────────────────────────────────────────────
    op.create_table(
        "project_permissions",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column(
            "operation",
            sa.Enum(
                "list",
                "get",
                "create",
                "replace",
                "update",
                "delete",
                "head",
                name="auth_operation",
                native_enum=False,
                length=15,
            ),
            nullable=False,
        ),
        # TEXT[] array — native Postgres; no junction table needed for role lists
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(length=60)),
            nullable=False,
        ),
        sa.Column(
            "row_rule",
            sa.Enum(
                "owner",
                "role_scoped",
                "tenant",
                "custom_filter",
                name="row_rule",
                native_enum=False,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("custom_filter_field", sa.String(length=100), nullable=True),
        sa.Column("custom_filter_value", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "entity_id",
            "operation",
            name="uq_project_permissions_project_entity_op",
        ),
    )
    op.create_index(
        "ix_project_permissions_project_id",
        "project_permissions",
        ["project_id"],
    )

    # ── auth_custom_fields ────────────────────────────────────────────────────
    op.create_table(
        "auth_custom_fields",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "string",
                "text",
                "integer",
                "float",
                "boolean",
                "date",
                "datetime",
                "email",
                "phone",
                "url",
                "enum",
                name="auth_custom_field_type",
                native_enum=False,
                length=15,
            ),
            nullable=False,
        ),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("unique", sa.Boolean(), nullable=False),
        sa.Column("indexed", sa.Boolean(), nullable=False),
        sa.Column("min_length", sa.Integer(), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("default_value", sa.String(length=500), nullable=True),
        sa.Column(
            "enum_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_auth_custom_fields_project_name"
        ),
    )
    op.create_index(
        "ix_auth_custom_fields_project_id",
        "auth_custom_fields",
        ["project_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_auth_custom_fields_project_id", table_name="auth_custom_fields")
    op.drop_table("auth_custom_fields")
    op.drop_index("ix_project_permissions_project_id", table_name="project_permissions")
    op.drop_table("project_permissions")
    op.drop_index("ix_project_roles_project_id", table_name="project_roles")
    op.drop_table("project_roles")
    op.drop_table("project_auth_configs")
