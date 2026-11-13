"""operations pack: prediction

Revision ID: 0036
Revises: 0035
Create Date: rendered from the spec by Backend Builder

Logged predictions with an integer interval and an actual that is filled in later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prediction_records",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject_ref", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("low", sa.BigInteger(), nullable=False),
        sa.Column("high", sa.BigInteger(), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual", sa.BigInteger(), nullable=True),
        sa.Column("actual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("low <= value AND value <= high", name="ck_prediction_records_interval"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_prediction_records_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prediction_records_tenant_id"), "prediction_records", ["tenant_id"], unique=False)
    op.create_index("ix_prediction_records_kind", "prediction_records", ["tenant_id", "kind", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("prediction_records")
