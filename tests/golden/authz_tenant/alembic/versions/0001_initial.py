"""initial schema

Revision ID: 0001
Revises:
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_labels"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
    )
    op.create_table(
        "tasks_labels",
        sa.Column("left_id", sa.Uuid(), nullable=False),
        sa.Column("right_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["left_id"], ["tasks.id"], name="fk_tasks_labels_left_id_tasks", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["right_id"], ["labels.id"], name="fk_tasks_labels_right_id_labels", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("left_id", "right_id", name="pk_tasks_labels"),
    )


def downgrade() -> None:
    op.drop_table("tasks_labels")
    op.drop_table("tasks")
    op.drop_table("labels")
