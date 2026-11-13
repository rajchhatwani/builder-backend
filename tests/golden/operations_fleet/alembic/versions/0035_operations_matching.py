"""operations pack: matching

Revision ID: 0035
Revises: 0034
Create Date: rendered from the spec by Backend Builder

Assignments with a partial UNIQUE index: one active (offered / accepted) assignment per request.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_assignments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("request_ref", sa.String(length=128), nullable=False),
        sa.Column("candidate_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="offered", nullable=False),
        sa.Column("score", sa.BigInteger(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("status IN ('offered', 'accepted', 'rejected', 'expired')", name="ck_match_assignments_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_match_assignments_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_match_assignments_tenant_id"), "match_assignments", ["tenant_id"], unique=False)
    op.create_index("ix_match_assignments_request", "match_assignments", ["tenant_id", "request_ref"], unique=False)
    op.create_index(
        "uq_match_assignments_active",
        "match_assignments",
        ["tenant_id", "request_ref"],
        unique=True,
        postgresql_where=sa.text("status IN ('offered', 'accepted')"),
    )


def downgrade() -> None:
    op.drop_table("match_assignments")
