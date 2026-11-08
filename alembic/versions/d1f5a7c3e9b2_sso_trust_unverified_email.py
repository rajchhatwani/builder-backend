"""OIDC connections: opt-in to trust an IdP that sends no `email_verified` claim

New connections require the claim. Connections that exist today keep working as they did
(they were accepted without it), so they are switched on; their admins can turn it off.

Revision ID: d1f5a7c3e9b2
Revises: c8a4e6b2d9f1
Create Date: 2026-10-28
"""

import sqlalchemy as sa

from alembic import op

revision = "d1f5a7c3e9b2"
down_revision = "c8a4e6b2d9f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sso_connections",
        sa.Column(
            "trust_unverified_email", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.execute("UPDATE sso_connections SET trust_unverified_email = true WHERE protocol = 'oidc'")


def downgrade() -> None:
    op.drop_column("sso_connections", "trust_unverified_email")
