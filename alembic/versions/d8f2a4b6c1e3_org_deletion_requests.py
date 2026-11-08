"""organizations: deletion requests with a grace period

Revision ID: d8f2a4b6c1e3
Revises: c7e1f3a9d2b4
Create Date: 2026-10-26

Owner decision: deleting an org is a request. Access is blocked from the request; the owner
can revoke it until the scheduled time, when the org and its projects are deleted.
"""

import sqlalchemy as sa

from alembic import op

revision = "d8f2a4b6c1e3"
down_revision = "c7e1f3a9d2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "deletion_requested_by",
            sa.UUID(),
            sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # The deletion job looks for due requests.
    op.create_index(
        "ix_organizations_deletion_due",
        "organizations",
        ["deletion_scheduled_for"],
        postgresql_where=sa.text("deletion_scheduled_for IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_deletion_due", table_name="organizations")
    op.drop_column("organizations", "deletion_requested_by")
    op.drop_column("organizations", "deletion_scheduled_for")
    op.drop_column("organizations", "deletion_requested_at")
