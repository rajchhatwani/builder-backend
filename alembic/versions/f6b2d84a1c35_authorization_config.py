"""authorization config

Revision ID: f6b2d84a1c35
Revises: e5a1c93b7d42
Create Date: 2026-10-24 18:00:00.000000

Adds the project_authorizations table (ABAC / PBAC policies of a project).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f6b2d84a1c35"
down_revision: str | Sequence[str] | None = "e5a1c93b7d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_authorizations",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=8), nullable=False),
        sa.Column("policies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
        sa.CheckConstraint(
            "model in ('rbac', 'abac', 'pbac')", name="ck_project_authorizations_model"
        ),
    )


def downgrade() -> None:
    op.drop_table("project_authorizations")
