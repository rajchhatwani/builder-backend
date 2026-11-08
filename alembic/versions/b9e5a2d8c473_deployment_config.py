"""deployment config

Revision ID: b9e5a2d8c473
Revises: a8d4f1c7b362
Create Date: 2026-10-24 22:00:00.000000

Adds the project_deployments table (cloud deployment settings of a project).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b9e5a2d8c473"
down_revision: str | Sequence[str] | None = "a8d4f1c7b362"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_deployments",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cloud", sa.String(length=8), nullable=False),
        sa.Column("region", sa.String(length=40), nullable=False),
        sa.Column("github_repo", sa.String(length=140), nullable=False),
        sa.Column("environments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_deployments")
