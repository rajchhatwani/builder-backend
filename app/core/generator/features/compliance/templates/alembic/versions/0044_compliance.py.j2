"""compliance: legal holds, consent, break-glass grants, audit, retention runs

Revision ID: 0044
Revises: 0043
Create Date: rendered from the spec by Backend Builder

`compliance_audit.detail` holds ids and counts only, never a field value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_holds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity", sa.String(80), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("placed_by", sa.String(64), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(64), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_legal_holds"),
    )
    op.create_index("ix_legal_holds_entity", "legal_holds", ["entity", "record_id"])
    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
    )
    op.create_index("ix_consents_subject", "consents", ["subject", "purpose"])
    op.create_table(
        "break_glass_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("entity_scope", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_break_glass_grants"),
    )
    op.create_index("ix_break_glass_grants_user", "break_glass_grants", ["user_id"])
    op.create_table(
        "compliance_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity", sa.String(80), nullable=True),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_compliance_audit"),
    )
    op.create_index("ix_compliance_audit_at", "compliance_audit", ["at"])
    op.create_table(
        "retention_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_retention_runs"),
    )


def downgrade() -> None:
    op.drop_table("retention_runs")
    op.drop_index("ix_compliance_audit_at", table_name="compliance_audit")
    op.drop_table("compliance_audit")
    op.drop_index("ix_break_glass_grants_user", table_name="break_glass_grants")
    op.drop_table("break_glass_grants")
    op.drop_index("ix_consents_subject", table_name="consents")
    op.drop_table("consents")
    op.drop_index("ix_legal_holds_entity", table_name="legal_holds")
    op.drop_table("legal_holds")
