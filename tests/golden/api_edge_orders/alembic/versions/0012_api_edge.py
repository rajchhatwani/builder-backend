"""api edge

Revision ID: 0012
Revises: 0002
Create Date: rendered from the spec by Backend Builder

Idempotency keys, rate-limit buckets and quota counters.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_key", sa.String(64), nullable=False),
        sa.Column("principal_key", sa.String(80), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.Column("response_body", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_api_idempotency"),
        sa.UniqueConstraint("tenant_key", "principal_key", "key", name="uq_api_idempotency_scope_key"),
    )
    op.create_index("ix_api_idempotency_expires_at", "api_idempotency", ["expires_at"])
    op.create_table(
        "api_rate_buckets",
        sa.Column("bucket_key", sa.String(200), nullable=False),
        sa.Column("tokens", sa.Double(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key", name="pk_api_rate_buckets"),
    )
    op.create_index("ix_api_rate_buckets_updated_at", "api_rate_buckets", ["updated_at"])
    op.create_table(
        "api_quota_usage",
        sa.Column("tenant_key", sa.String(64), nullable=False),
        sa.Column("meter", sa.String(40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_key", "meter", "period_start", name="pk_api_quota_usage"),
    )


def downgrade() -> None:
    op.drop_table("api_quota_usage")
    op.drop_index("ix_api_rate_buckets_updated_at", table_name="api_rate_buckets")
    op.drop_table("api_rate_buckets")
    op.drop_index("ix_api_idempotency_expires_at", table_name="api_idempotency")
    op.drop_table("api_idempotency")
