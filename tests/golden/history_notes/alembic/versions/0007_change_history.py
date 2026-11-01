"""change history

Revision ID: 0007
Revises: 0005
Create Date: rendered from the spec by Backend Builder

The change log: old and new value of every audited field change, with the actor.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ch_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity", sa.String(80), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(80), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("op", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ch_changes"),
    )
    op.create_index("ix_ch_changes_record", "ch_changes", ["entity", "record_id", "created_at"])
    op.create_index("ix_ch_changes_created_at", "ch_changes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ch_changes_created_at", table_name="ch_changes")
    op.drop_index("ix_ch_changes_record", table_name="ch_changes")
    op.drop_table("ch_changes")
