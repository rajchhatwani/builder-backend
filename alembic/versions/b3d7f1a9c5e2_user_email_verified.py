"""platform_users.email_verified_at (review F-005: pre-hijack and invite-by-id)

Revision ID: b3d7f1a9c5e2
Revises: a9c4e2f7b1d3
Create Date: 2026-10-27
"""

import sqlalchemy as sa

from alembic import op

revision = "b3d7f1a9c5e2"
down_revision = "a9c4e2f7b1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Accounts that only exist through an IdP (SSO-only password) proved their mailbox there.
    op.execute(
        "UPDATE platform_users SET email_verified_at = created_at WHERE password_hash = '!sso-only'"
    )


def downgrade() -> None:
    op.drop_column("platform_users", "email_verified_at")
