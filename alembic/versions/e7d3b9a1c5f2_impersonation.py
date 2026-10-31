"""Impersonation (§4.5, §7.1): per-org consent, operator "view as" sessions

- organizations.allow_impersonation: default on (support can help); an org can turn it off.
- impersonation_sessions: one row per "view as" session; the access token only names it.
- platform_audit_log.via widens to 20 characters so it can say "impersonation".

Revision ID: e7d3b9a1c5f2
Revises: d1f5a7c3e9b2
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e7d3b9a1c5f2"
down_revision = "d1f5a7c3e9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("allow_impersonation", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "impersonation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("writes_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_impersonation_org", "impersonation_sessions", ["organization_id", "created_at"]
    )
    op.create_index(
        "ix_impersonation_operator", "impersonation_sessions", ["operator_id", "created_at"]
    )
    op.alter_column("platform_audit_log", "via", existing_type=sa.String(10), type_=sa.String(20))


def downgrade() -> None:
    # `via` stays 20 wide: the audit log is append-only (a trigger refuses UPDATE), so rows that
    # say "impersonation" cannot be shortened.
    op.drop_table("impersonation_sessions")
    op.drop_column("organizations", "allow_impersonation")
