"""Requirements map: items, clarifying questions, sources (B3-6)

Revision ID: b30a0000002b
Revises: b30a0000002a
Create Date: 2026-11-02

Project-child tables with the usual tenant_isolation policy (enabling RLS stays a separate step).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a0000002b"
down_revision: str | Sequence[str] | None = "b30a0000002a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CTX = "nullif(current_setting('app.organization_id', true), '')"
_TABLES = ("requirements_maps", "requirement_items", "requirement_questions")


def upgrade() -> None:
    op.create_table(
        "requirements_maps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_requirements_maps_project", "requirements_maps", ["project_id"], unique=True)
    op.create_table(
        "requirement_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("map_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.String(length=600), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=True),
        sa.Column("value", sa.String(length=200), nullable=True),
        sa.Column("source_doc", sa.String(length=200), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("covered_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["requirements_maps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirement_items_map", "requirement_items", ["map_id", "created_at"])
    op.create_table(
        "requirement_questions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("map_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.String(length=600), nullable=False),
        sa.Column("assumption", sa.String(length=600), nullable=False),
        sa.Column("answer", sa.String(length=2000), nullable=True),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["requirements_maps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirement_questions_map", "requirement_questions", ["map_id", "created_at"])
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"({_CTX} IS NULL OR project_id IN (SELECT id FROM projects))"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_requirement_questions_map", table_name="requirement_questions")
    op.drop_table("requirement_questions")
    op.drop_index("ix_requirement_items_map", table_name="requirement_items")
    op.drop_table("requirement_items")
    op.drop_index("uq_requirements_maps_project", table_name="requirements_maps")
    op.drop_table("requirements_maps")
