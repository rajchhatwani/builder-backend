"""Verified e-mail sign-up for platform accounts (CO3-7, F-5 + F-9)

Adds `platform_email_verification_tokens` (hashed at rest, single use, expiring). Not an
org-scoped table, so no RLS policy (same as `platform_refresh_tokens`).
Accounts that exist before this migration are treated as verified: their
`email_verified_at` is backfilled from `created_at`, so nothing is locked out.

Revision ID: b30a00000022
Revises: a7c3e9d1f4b6
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b30a00000022"
down_revision = "a7c3e9d1f4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_email_verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_platform_email_verification_user", "platform_email_verification_tokens", ["user_id"]
    )
    op.execute(
        "UPDATE platform_users SET email_verified_at = created_at WHERE email_verified_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_email_verification_user", table_name="platform_email_verification_tokens"
    )
    op.drop_table("platform_email_verification_tokens")
