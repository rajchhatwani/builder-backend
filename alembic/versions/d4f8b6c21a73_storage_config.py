"""storage config

Revision ID: d4f8b6c21a73
Revises: c7d2a41e9b05
Create Date: 2026-10-24 12:00:00.000000

Adds the project_storage_configs table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4f8b6c21a73"
down_revision: str | Sequence[str] | None = "c7d2a41e9b05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_storage_configs",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "backend",
            sa.Enum("s3", "minio", name="storage_backend", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("key_prefix", sa.String(length=100), nullable=False),
        sa.Column("allowed_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_file_mb", sa.Integer(), nullable=False),
        sa.Column("user_quota_mb", sa.Integer(), nullable=True),
        sa.Column("uploads_per_hour", sa.Integer(), nullable=False),
        sa.Column(
            "download_mode",
            sa.Enum("proxy", "presigned", name="download_mode", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("allow_inline_images", sa.Boolean(), nullable=False),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("security", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_storage_configs")
