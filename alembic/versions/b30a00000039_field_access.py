"""Field-level access rules (B4-7)

Revision ID: b30a00000039
Revises: b30a00000038
Create Date: 2026-11-09

project_authorizations.field_access holds the field layer of the access model (who may read or
write one field). No new table, so the RLS list is unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b30a00000039"
down_revision: str | Sequence[str] | None = "b30a00000038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_authorizations",
        sa.Column(
            "field_access", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("project_authorizations", "field_access")
