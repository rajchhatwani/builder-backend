"""Upgrade engine: generation base storage and upgrade proposals (CP-6E)

Revision ID: b30a00000041
Revises: b30a00000040
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a00000041"
down_revision: str | Sequence[str] | None = "b30a00000040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("generator_version", sa.String(32), nullable=True))
    op.add_column(
        "generations",
        sa.Column("block_versions", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("generations", sa.Column("file_blob", sa.LargeBinary(), nullable=True))
    op.create_table(
        "upgrade_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("base_generation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("from_generator_version", sa.String(32), nullable=True),
        sa.Column("to_generator_version", sa.String(32), nullable=False),
        sa.Column("block_changes", postgresql.JSONB(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),
        sa.Column("patch_text", sa.Text(), nullable=False),
        sa.Column("sbom_diff", postgresql.JSONB(), nullable=False),
        sa.Column("migrations", postgresql.JSONB(), nullable=False),
        sa.Column("scorecard", postgresql.JSONB(), nullable=False),
        sa.Column("auto_apply_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_upgrade_proposals_project_created", "upgrade_proposals", ["project_id", "created_at"])
    op.create_index(
        "uq_upgrade_proposals_open",
        "upgrade_proposals",
        ["project_id", "base_generation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    # RLS: same policy as the other project-scoped tables (installed by `python -m app.core.rls`).
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON upgrade_proposals")
    op.execute(
        "CREATE POLICY tenant_isolation ON upgrade_proposals USING "
        "(nullif(current_setting('app.organization_id', true), '') IS NULL "
        "OR project_id IN (SELECT id FROM projects))"
    )


def downgrade() -> None:
    op.drop_table("upgrade_proposals")
    op.drop_column("generations", "file_blob")
    op.drop_column("generations", "block_versions")
    op.drop_column("generations", "generator_version")
