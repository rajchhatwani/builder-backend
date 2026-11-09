"""Realtime gateway: project event log and retention floor (B4-2)

Revision ID: b30a0000003c
Revises: b30a0000003b
Create Date: 2026-11-09

Two project-scoped tables (listed in app/core/rls.py PROJECT_CHILD_TABLES). The tenant_isolation
policy is installed here; turning RLS on stays `python -m app.core.rls enable --yes`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b30a0000003c"
down_revision: str | Sequence[str] | None = "b30a0000003b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("realtime_events", "realtime_floors")


def upgrade() -> None:
    op.create_table(
        "realtime_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(length=60), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_realtime_events_project_id", "realtime_events", ["project_id", "id"])
    op.create_index("ix_realtime_events_created", "realtime_events", ["created_at"])
    op.create_table(
        "realtime_floors",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("floor_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("realtime_floors")
    op.drop_index("ix_realtime_events_created", table_name="realtime_events")
    op.drop_index("ix_realtime_events_project_id", table_name="realtime_events")
    op.drop_table("realtime_events")
