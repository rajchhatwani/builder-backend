"""Usage metering: events, counters, limits (B4-5)

Revision ID: b30a0000003b
Revises: b30a0000003a
Create Date: 2026-11-09

Three org tables (tenant_isolation policy like the other org tables; enabling RLS stays a
separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a0000003b"
down_revision: str | Sequence[str] | None = "b30a0000003a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("usage_events", "usage_counters", "usage_limits")


def upgrade() -> None:
    org_fk = lambda: sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE")  # noqa: E731
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        org_fk(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_org", "usage_events", ["organization_id", "created_at"])
    op.create_index(
        "uq_usage_events_idem",
        "usage_events",
        ["organization_id", "metric", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL AND outcome = 'granted'"),
    )
    op.create_table(
        "usage_counters",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=False),
        org_fk(),
        sa.PrimaryKeyConstraint("organization_id", "metric", "period_start"),
    )
    op.create_table(
        "usage_limits",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        org_fk(),
        sa.ForeignKeyConstraint(["updated_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("organization_id", "metric"),
    )
    for t in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING "
            f"({_CTX} IS NULL OR organization_id = {_CTX}::uuid)"
        )


def downgrade() -> None:
    for t in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.drop_table(t)
