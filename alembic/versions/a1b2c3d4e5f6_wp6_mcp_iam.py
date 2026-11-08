"""WP6 MCP IAM

Revision ID: a1b2c3d4e5f6
Revises: c1f6b3e9d584
Create Date: 2026-10-26 01:00:00.000000

Adds:
  - project_members.mcp_enabled  (per-member MCP access grant, default False)
  - platform_api_tokens.description  (human label for the token)
  - platform_api_tokens.last_mcp_use_at  (last time token was used for an MCP call)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "c1f6b3e9d584"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_members",
        sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "platform_api_tokens",
        sa.Column("description", sa.String(255), nullable=True),
    )
    op.add_column(
        "platform_api_tokens",
        sa.Column("last_mcp_use_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_api_tokens", "last_mcp_use_at")
    op.drop_column("platform_api_tokens", "description")
    op.drop_column("project_members", "mcp_enabled")
