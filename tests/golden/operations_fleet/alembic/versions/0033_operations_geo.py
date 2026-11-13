"""operations pack: geo

Revision ID: 0033
Revises: 0002
Create Date: rendered from the spec by Backend Builder

Places (with a grid cell index), geofences, memberships (UNIQUE subject + geofence) and the enter / exit event log.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _now() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "geo_places",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=True),
        sa.Column("lat_micro", sa.Integer(), nullable=False),
        sa.Column("lng_micro", sa.Integer(), nullable=False),
        sa.Column("cell", sa.BigInteger(), nullable=False),
        _now(),
        sa.CheckConstraint("lat_micro BETWEEN -90000000 AND 90000000", name="ck_geo_places_lat"),
        sa.CheckConstraint("lng_micro BETWEEN -180000000 AND 180000000", name="ck_geo_places_lng"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_geo_places_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_geo_places_tenant_id"), "geo_places", ["tenant_id"], unique=False)
    op.create_index("ix_geo_places_cell", "geo_places", ["tenant_id", "cell"], unique=False)

    op.create_table(
        "geo_geofences",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("shape", sa.String(length=8), nullable=False),
        sa.Column("center_lat_micro", sa.Integer(), nullable=True),
        sa.Column("center_lng_micro", sa.Integer(), nullable=True),
        sa.Column("radius_m", sa.Integer(), nullable=True),
        sa.Column("vertices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("min_lat_micro", sa.Integer(), nullable=False),
        sa.Column("max_lat_micro", sa.Integer(), nullable=False),
        sa.Column("min_lng_micro", sa.Integer(), nullable=False),
        sa.Column("max_lng_micro", sa.Integer(), nullable=False),
        _now(),
        sa.CheckConstraint("shape IN ('circle', 'polygon')", name="ck_geo_geofences_shape"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_geo_geofences_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_geo_geofences_tenant_id"), "geo_geofences", ["tenant_id"], unique=False)

    op.create_table(
        "geo_memberships",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("geofence_id", sa.Uuid(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["geofence_id"], ["geo_geofences.id"], name="fk_geo_memberships_geofence_id_geo_geofences", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_geo_memberships_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "geofence_id", name="uq_geo_memberships_subject_id_geofence_id"),
    )
    op.create_index(op.f("ix_geo_memberships_tenant_id"), "geo_memberships", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_geo_memberships_geofence_id"), "geo_memberships", ["geofence_id"], unique=False)

    op.create_table(
        "geo_events",
        _id(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("geofence_id", sa.Uuid(), nullable=False),
        sa.Column("geofence_name", sa.String(length=200), nullable=False),
        sa.Column("event", sa.String(length=5), nullable=False),
        sa.Column("lat_micro", sa.Integer(), nullable=False),
        sa.Column("lng_micro", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("event IN ('enter', 'exit')", name="ck_geo_events_event"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_geo_events_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_geo_events_tenant_id"), "geo_events", ["tenant_id"], unique=False)
    op.create_index("ix_geo_events_subject", "geo_events", ["tenant_id", "subject_id", "occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_table("geo_events")
    op.drop_table("geo_memberships")
    op.drop_table("geo_geofences")
    op.drop_table("geo_places")
