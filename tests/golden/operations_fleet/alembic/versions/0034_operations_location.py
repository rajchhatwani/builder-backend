"""operations pack: location

Revision ID: 0034
Revises: 0033
Create Date: rendered from the spec by Backend Builder

Latest position per subject (UNIQUE subject) and a bounded history (UNIQUE subject + seq).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "location_positions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=True),
        sa.Column("lat_micro", sa.Integer(), nullable=False),
        sa.Column("lng_micro", sa.Integer(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("seq >= 0", name="ck_location_positions_seq"),
        sa.CheckConstraint("lat_micro BETWEEN -90000000 AND 90000000", name="ck_location_positions_lat"),
        sa.CheckConstraint("lng_micro BETWEEN -180000000 AND 180000000", name="ck_location_positions_lng"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_location_positions_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "subject_id", name="uq_location_positions_subject"),
    )
    op.create_index(op.f("ix_location_positions_tenant_id"), "location_positions", ["tenant_id"], unique=False)
    op.create_index("ix_location_positions_box", "location_positions", ["tenant_id", "lat_micro", "lng_micro"], unique=False)

    op.create_table(
        "location_history",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("lat_micro", sa.Integer(), nullable=False),
        sa.Column("lng_micro", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_location_history_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "subject_id", "seq", name="uq_location_history_subject_seq"),
    )
    op.create_index(op.f("ix_location_history_tenant_id"), "location_history", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("location_history")
    op.drop_table("location_positions")
