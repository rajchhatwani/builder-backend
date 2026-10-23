"""keycloak config

Revision ID: b3e1f7a92c64
Revises: 925303a40baa
Create Date: 2026-10-23 12:00:00.000000

Adds project_auth_configs.provider and the project_keycloak_configs table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3e1f7a92c64"
down_revision: str | Sequence[str] | None = "925303a40baa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_auth_configs",
        sa.Column(
            "provider",
            sa.Enum("builtin", "keycloak", name="auth_provider", native_enum=False, length=10),
            nullable=False,
            server_default="builtin",
        ),
    )
    op.create_table(
        "project_keycloak_configs",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum("own", "shared", name="keycloak_mode", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("realm", sa.String(length=63), nullable=False),
        sa.Column("api_client_id", sa.String(length=100), nullable=False),
        sa.Column("web_client_id", sa.String(length=100), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("password_min_length", sa.Integer(), nullable=False),
        sa.Column(
            "mfa",
            sa.Enum(
                "off", "optional", "required", name="keycloak_mfa", native_enum=False, length=10
            ),
            nullable=False,
        ),
        sa.Column("session_idle_minutes", sa.Integer(), nullable=False),
        sa.Column("session_max_hours", sa.Integer(), nullable=False),
        sa.Column("audit_retention_days", sa.Integer(), nullable=False),
        sa.Column("identity_providers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_project_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_keycloak_configs")
    op.drop_column("project_auth_configs", "provider")
