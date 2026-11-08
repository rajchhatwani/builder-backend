"""Dependency approvals expire and can be revoked; one open request per pin (B3-9 fix round)

Revision ID: b30a00000029
Revises: b30a00000028
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a00000029"
down_revision: str | Sequence[str] | None = "b30a00000028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dependency_requests", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("dependency_requests", sa.Column("revoked_by", sa.UUID()))
    op.add_column("dependency_requests", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_dependency_requests_revoked_by",
        "dependency_requests",
        "platform_users",
        ["revoked_by"],
        ["id"],
        ondelete="SET NULL",
    )
    # Approvals made before expiry existed get the default window from now.
    op.execute(
        "UPDATE dependency_requests SET expires_at = now() + interval '90 days' "
        "WHERE status = 'approved' AND expires_at IS NULL"
    )
    op.create_index(
        "uq_dependency_requests_open",
        "dependency_requests",
        ["project_id", "package", "version"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
    )


def downgrade() -> None:
    op.drop_index("uq_dependency_requests_open", table_name="dependency_requests")
    op.drop_constraint("fk_dependency_requests_revoked_by", "dependency_requests", type_="foreignkey")
    op.drop_column("dependency_requests", "revoked_at")
    op.drop_column("dependency_requests", "revoked_by")
    op.drop_column("dependency_requests", "expires_at")
