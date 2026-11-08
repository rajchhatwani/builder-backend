"""enterprise SSO: sso_connections, sso_domains, sso_login_requests

Revision ID: e4b9c2d7a1f5
Revises: d8f2a4b6c1e3
Create Date: 2026-10-26

PLATFORM_SAAS_PLAN §3.1 tables, plus:
  - sso_connections.jit_enabled / jit_role: the "allowed roles for JIT" setting (§12.D.4);
  - sso_connections.updated_at;
  - sso_domains.created_at;
  - sso_login_requests: one-time state of a login in flight (SAML InResponseTo / OIDC state).
"""

import sqlalchemy as sa

from alembic import op

revision = "e4b9c2d7a1f5"
down_revision = "d8f2a4b6c1e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sso_connections",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("protocol", sa.String(10), nullable=False),
        sa.Column("idp_entity_id", sa.String(500), nullable=True),
        sa.Column("idp_sso_url", sa.String(500), nullable=True),
        sa.Column("idp_cert_pem", sa.Text(), nullable=True),
        sa.Column("oidc_discovery_url", sa.String(500), nullable=True),
        sa.Column("oidc_client_id", sa.String(255), nullable=True),
        sa.Column("oidc_client_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("jit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("jit_role", sa.String(20), nullable=False, server_default="member"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("protocol IN ('saml', 'oidc')", name="ck_sso_connections_protocol"),
        sa.CheckConstraint("jit_role IN ('member', 'admin')", name="ck_sso_connections_jit_role"),
    )
    op.create_table(
        "sso_domains",
        sa.Column("domain", sa.String(253), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dns_token", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("domain = lower(domain)", name="ck_sso_domains_lower"),
    )
    op.create_index("ix_sso_domains_org", "sso_domains", ["organization_id"])
    op.create_table(
        "sso_login_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("protocol", sa.String(10), nullable=False),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=True),
        sa.Column("code_verifier", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sso_login_requests_expires", "sso_login_requests", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sso_login_requests_expires", table_name="sso_login_requests")
    op.drop_table("sso_login_requests")
    op.drop_index("ix_sso_domains_org", table_name="sso_domains")
    op.drop_table("sso_domains")
    op.drop_table("sso_connections")
