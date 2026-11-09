"""Metrics layer and scheduled reports (B4-4)

Revision ID: b30a0000003d
Revises: b30a0000003c
Create Date: 2026-11-09

Three project-scoped tables (listed in app/core/rls.py PROJECT_CHILD_TABLES). The tenant_isolation
policy is installed here; turning RLS on stays `python -m app.core.rls enable --yes`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b30a0000003d"
down_revision: str | Sequence[str] | None = "b30a0000003c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("metrics", "reports", "report_runs")


def _pk() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _project() -> sa.Column[object]:
    return sa.Column(
        "project_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "metrics",
        _pk(),
        _project(),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "key", name="uq_metrics_project_key"),
    )
    op.create_table(
        "reports",
        _pk(),
        _project(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("metric_keys", postgresql.JSONB(), nullable=False),
        sa.Column("schedule", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reports_project", "reports", ["project_id"])
    op.create_table(
        "report_runs",
        _pk(),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _project(),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("values", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "scheduled_for", name="uq_report_runs_slot"),
    )
    op.create_index("ix_report_runs_project", "report_runs", ["project_id"])
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_report_runs_project", table_name="report_runs")
    op.drop_table("report_runs")
    op.drop_index("ix_reports_project", table_name="reports")
    op.drop_table("reports")
    op.drop_table("metrics")
