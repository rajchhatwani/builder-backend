"""auth secrets table

Revision ID: 925303a40baa
Revises: aa9d78f96e73
Create Date: 2026-10-23 03:08:00.000000

Adds project_auth_secrets table for encrypted credential storage.
All columns are TEXT (Fernet ciphertext); None = not configured.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "925303a40baa"
down_revision: str | Sequence[str] | None = "aa9d78f96e73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_auth_secrets",
        sa.Column("project_id", sa.UUID(), nullable=False),
        # SMTP
        sa.Column("smtp_username", sa.Text(), nullable=True),
        sa.Column("smtp_password", sa.Text(), nullable=True),
        # Twilio
        sa.Column("twilio_account_sid", sa.Text(), nullable=True),
        sa.Column("twilio_auth_token", sa.Text(), nullable=True),
        # Vonage
        sa.Column("vonage_api_key", sa.Text(), nullable=True),
        sa.Column("vonage_api_secret", sa.Text(), nullable=True),
        # AWS SNS
        sa.Column("aws_access_key_id", sa.Text(), nullable=True),
        sa.Column("aws_secret_access_key", sa.Text(), nullable=True),
        sa.Column("aws_region", sa.Text(), nullable=True),
        # Standard columns
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),  # 1:1 with projects
    )
    op.create_index(
        "ix_project_auth_secrets_project_id",
        "project_auth_secrets",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_auth_secrets_project_id",
        table_name="project_auth_secrets",
    )
    op.drop_table("project_auth_secrets")
