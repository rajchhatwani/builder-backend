"""Data import: batches, rows, canonical records (B4-1)

Revision ID: b30a0000003a
Revises: b30a00000039
Create Date: 2026-11-09

Three project-scoped tables (all carry project_id; listed in app/core/rls.py PROJECT_CHILD_TABLES).
The tenant_isolation policy is installed here; turning RLS on stays `python -m app.core.rls enable --yes`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b30a0000003a"
down_revision: str | Sequence[str] | None = "b30a00000039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("import_batches", "import_rows", "imported_records")


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
        "import_batches",
        _pk(),
        _project(),
        sa.Column("entity_name", sa.String(120), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("headers", postgresql.JSONB(), nullable=False),
        sa.Column("mapping", postgresql.JSONB(), nullable=False),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_import_batches_project", "import_batches", ["project_id", "created_at"])
    op.create_table(
        "import_rows",
        _pk(),
        _project(),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("record", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=True),
    )
    op.create_index("ix_import_rows_batch", "import_rows", ["batch_id", "row_no"])
    op.create_index("ix_import_rows_batch_status", "import_rows", ["batch_id", "status"])
    op.create_table(
        "imported_records",
        _pk(),
        _project(),
        sa.Column("entity_name", sa.String(120), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("import_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "entity_name", "dedupe_key", name="uq_imported_records_key"),
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("imported_records")
    op.drop_index("ix_import_rows_batch_status", table_name="import_rows")
    op.drop_index("ix_import_rows_batch", table_name="import_rows")
    op.drop_table("import_rows")
    op.drop_index("ix_import_batches_project", table_name="import_batches")
    op.drop_table("import_batches")
