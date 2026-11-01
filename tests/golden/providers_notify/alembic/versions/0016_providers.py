"""provider credentials

Revision ID: 0016
Revises: 0002
Create Date: rendered from the spec by Backend Builder

The per-tenant credential vault: ciphertext only, never a plaintext secret.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("key_name", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_provider_credentials"),
        sa.UniqueConstraint("tenant_id", "provider", "key_name", name="uq_provider_credentials_key"),
    )
    op.create_index(
        "ix_provider_credentials_tenant", "provider_credentials", ["tenant_id", "provider"]
    )


def downgrade() -> None:
    op.drop_index("ix_provider_credentials_tenant", table_name="provider_credentials")
    op.drop_table("provider_credentials")
