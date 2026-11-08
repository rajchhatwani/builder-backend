"""authentication tables (Keycloak)

Revision ID: 0002
Revises: 0001
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_tenants"),
        sa.UniqueConstraint("external_ref", name="uq_auth_tenants_external_ref"),
    )
    op.create_table(
        "auth_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("roles", postgresql.JSONB(), nullable=False),
        sa.Column("role_source", sa.String(10), nullable=False, server_default="idp"),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_users"),
    )
    op.create_index("ix_auth_users_email", "auth_users", ["email"])
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("email_at_link", sa.String(320), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.id"],
            name="fk_auth_identities_user_id_auth_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_identities"),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_identities_issuer_subject"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sid", sa.String(255), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.id"],
            name="fk_auth_sessions_user_id_auth_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("issuer", "sid", name="uq_auth_sessions_issuer_sid"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "auth_provider_lock",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("realm", sa.String(63), nullable=True),
        sa.Column("issuer", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_provider_lock"),
    )
    op.add_column("tickets", sa.Column("created_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tickets_created_by_id_auth_users",
        "tickets",
        "auth_users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tickets_created_by_id", "tickets", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_created_by_id", table_name="tickets")
    op.drop_constraint("fk_tickets_created_by_id_auth_users", "tickets", type_="foreignkey")
    op.drop_column("tickets", "created_by_id")
    op.drop_table("auth_provider_lock")
    op.drop_table("auth_sessions")
    op.drop_table("auth_identities")
    op.drop_index("ix_auth_users_email", table_name="auth_users")
    op.drop_table("auth_users")
    op.drop_table("auth_tenants")
