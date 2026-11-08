"""built-in TOTP MFA, org security policies, SSO test results

Revision ID: f5c3a8e1b7d9
Revises: e4b9c2d7a1f5
Create Date: 2026-10-27

PLATFORM_SAAS_PLAN §4.4 Phase 1 and §8 "Security policies", plus §12.D.5–6:
  - platform_users.totp_secret_enc / totp_enabled_at / totp_last_step: TOTP (the secret is
    encrypted with app.core.crypto; the last used step stops a code being replayed);
  - mfa_recovery_codes: one-time backup codes, stored hashed;
  - platform_refresh_tokens.auth_methods: how the login family was authenticated ('pwd', 'pwd otp',
    'sso'), carried into every access token so policies can check it;
  - platform_refresh_tokens.family_started_at: when the sign-in happened (org session-TTL cap);
  - organizations.require_mfa / session_ttl_hours: the per-org policies;
  - sso_login_requests.purpose / test_user_id: "test with my own e-mail" logins;
  - sso_connections.last_test_*: the result of the last test, shown to admins and operators.
"""

import sqlalchemy as sa

from alembic import op

revision = "f5c3a8e1b7d9"
down_revision = "e4b9c2d7a1f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_users", sa.Column("totp_secret_enc", sa.Text(), nullable=True))
    op.add_column(
        "platform_users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("platform_users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("platform_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mfa_recovery_codes_user", "mfa_recovery_codes", ["user_id"])

    op.add_column(
        "platform_refresh_tokens",
        sa.Column("auth_methods", sa.String(40), nullable=False, server_default="pwd"),
    )
    op.add_column(
        "platform_refresh_tokens",
        sa.Column("family_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "organizations",
        sa.Column("require_mfa", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("organizations", sa.Column("session_ttl_hours", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_organizations_session_ttl",
        "organizations",
        "session_ttl_hours IS NULL OR (session_ttl_hours BETWEEN 1 AND 720)",
    )

    op.add_column(
        "sso_login_requests",
        sa.Column("purpose", sa.String(10), nullable=False, server_default="login"),
    )
    op.add_column("sso_login_requests", sa.Column("test_user_id", sa.UUID(), nullable=True))
    op.create_check_constraint(
        "ck_sso_login_requests_purpose", "sso_login_requests", "purpose IN ('login', 'test')"
    )
    op.add_column(
        "sso_connections", sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sso_connections", sa.Column("last_test_result", sa.String(60), nullable=True))
    op.add_column(
        "sso_connections",
        sa.Column(
            "last_tested_by",
            sa.UUID(),
            sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sso_connections", "last_tested_by")
    op.drop_column("sso_connections", "last_test_result")
    op.drop_column("sso_connections", "last_test_at")
    op.drop_constraint("ck_sso_login_requests_purpose", "sso_login_requests", type_="check")
    op.drop_column("sso_login_requests", "test_user_id")
    op.drop_column("sso_login_requests", "purpose")
    op.drop_constraint("ck_organizations_session_ttl", "organizations", type_="check")
    op.drop_column("organizations", "session_ttl_hours")
    op.drop_column("organizations", "require_mfa")
    op.drop_column("platform_refresh_tokens", "family_started_at")
    op.drop_column("platform_refresh_tokens", "auth_methods")
    op.drop_index("ix_mfa_recovery_codes_user", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_column("platform_users", "totp_last_step")
    op.drop_column("platform_users", "totp_enabled_at")
    op.drop_column("platform_users", "totp_secret_enc")
