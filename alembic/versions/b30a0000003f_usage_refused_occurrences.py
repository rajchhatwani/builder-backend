"""Coalesced refused-usage events (CP-4F3 WP-B)

Revision ID: b30a0000003f
Revises: b30a0000003e
Create Date: 2026-11-10

`usage_events.occurrences` counts how many refusals one (coalesced) event row stands for; granted
events and uncoalesced refusals keep 1.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b30a0000003f"
down_revision: str | Sequence[str] | None = "b30a0000003e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("occurrences", sa.BigInteger(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("usage_events", "occurrences")
