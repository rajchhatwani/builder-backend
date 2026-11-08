"""Org approval policy override and the approval payload hash

Revision ID: b30a00000034
Revises: b30a00000033
Create Date: 2026-11-08

B-001: `ai_org_settings.approval_policy` holds an org's override of the approval policy (it can only
tighten the platform policy; enforced in code). S1-004: `ai_approvals.payload_hash` binds an approval
to the exact payload that was asked, so a changed payload invalidates it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b30a00000034"
down_revision: str | Sequence[str] | None = "b30a00000033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_org_settings", sa.Column("approval_policy", postgresql.JSONB(), nullable=True))
    op.add_column("ai_approvals", sa.Column("payload_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_approvals", "payload_hash")
    op.drop_column("ai_org_settings", "approval_policy")
