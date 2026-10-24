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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_tenants"),
    )
    op.create_table(
        "auth_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("roles", postgresql.JSONB(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("born", sa.Date(), nullable=True),
        sa.Column("company", sa.String(80), nullable=True),
        sa.Column("mobile", sa.String(255), nullable=True),
        sa.Column("newsletter", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("plan", sa.String(64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("site", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["auth_tenants.id"],
            name="fk_auth_users_tenant_id_auth_tenants",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_users"),
    )
    op.create_index("ix_auth_users_email", "auth_users", ["email"])
    op.create_index("ix_auth_users_tenant_id", "auth_users", ["tenant_id"])
    op.create_index("ix_auth_users_site", "auth_users", ["site"])
    op.create_table(
        "auth_provider_lock",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("realm", sa.String(63), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_provider_lock"),
    )
    op.add_column("deals", sa.Column("created_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_deals_created_by_id_auth_users",
        "deals",
        "auth_users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_deals_created_by_id", "deals", ["created_by_id"])
    op.add_column("customers", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_customers_tenant_id_auth_tenants",
        "customers",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.add_column("deals", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_deals_tenant_id_auth_tenants",
        "deals",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_deals_tenant_id", "deals", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_customers_tenant_id", table_name="customers")
    op.drop_constraint("fk_customers_tenant_id_auth_tenants", "customers", type_="foreignkey")
    op.drop_column("customers", "tenant_id")
    op.drop_index("ix_deals_tenant_id", table_name="deals")
    op.drop_constraint("fk_deals_tenant_id_auth_tenants", "deals", type_="foreignkey")
    op.drop_column("deals", "tenant_id")
    op.drop_index("ix_deals_created_by_id", table_name="deals")
    op.drop_constraint("fk_deals_created_by_id_auth_users", "deals", type_="foreignkey")
    op.drop_column("deals", "created_by_id")
    op.drop_table("auth_provider_lock")
    op.drop_index("ix_auth_users_email", table_name="auth_users")
    op.drop_table("auth_users")
    op.drop_table("auth_tenants")
