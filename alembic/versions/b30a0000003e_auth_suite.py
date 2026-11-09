"""Suite membership on the auth config (B4-8)

Revision ID: b30a0000003e
Revises: b30a0000003d
Create Date: 2026-11-09

One nullable JSONB column holding the spec's auth.suite object ({suite_id, hub_issuer,
join_state}); NULL for every project that is not part of a suite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a0000003e"
down_revision: str | Sequence[str] | None = "b30a0000003d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_auth_configs", sa.Column("suite", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("project_auth_configs", "suite")
