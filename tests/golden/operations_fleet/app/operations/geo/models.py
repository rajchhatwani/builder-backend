"""Geo tables (generated). Places carry a grid `cell` column (indexed) for radius queries; geofence memberships are
UNIQUE(subject, geofence) so an enter / exit is decided by the database, not by a read-then-write."""

import datetime as _dt
import uuid as _uuid
from typing import Any

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


def _id() -> _orm.Mapped[_uuid.UUID]:
    return _orm.mapped_column(
        _sa.Uuid(), primary_key=True, default=_uuid.uuid4, server_default=_sa.text("gen_random_uuid()")
    )


def _created() -> _orm.Mapped[_dt.datetime]:
    return _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow, server_default=_sa.text("now()")
    )


class GeoPlace(_models_base.Base):
    __tablename__ = "geo_places"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_geo_places_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    kind: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(32), nullable=True)
    lat_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    lng_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    cell: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (
        _sa.Index("ix_geo_places_cell", "tenant_id", "cell"),
        _sa.CheckConstraint("lat_micro BETWEEN -90000000 AND 90000000", name="ck_geo_places_lat"),
        _sa.CheckConstraint("lng_micro BETWEEN -180000000 AND 180000000", name="ck_geo_places_lng"),
    )


class GeoGeofence(_models_base.Base):
    __tablename__ = "geo_geofences"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_geo_geofences_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    shape: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False)
    center_lat_micro: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    center_lng_micro: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    radius_m: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    vertices: _orm.Mapped[list[Any] | None] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    min_lat_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    max_lat_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    min_lng_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    max_lng_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (_sa.CheckConstraint("shape IN ('circle', 'polygon')", name="ck_geo_geofences_shape"),)


class GeoMembership(_models_base.Base):
    __tablename__ = "geo_memberships"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_geo_memberships_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    subject_id: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    geofence_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("geo_geofences.id", name="fk_geo_memberships_geofence_id_geo_geofences", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    since: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (_sa.UniqueConstraint("subject_id", "geofence_id", name="uq_geo_memberships_subject_id_geofence_id"),)


class GeoEvent(_models_base.Base):
    __tablename__ = "geo_events"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_geo_events_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    subject_id: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    geofence_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    geofence_name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    event: _orm.Mapped[str] = _orm.mapped_column(_sa.String(5), nullable=False)
    lat_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    lng_micro: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    occurred_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (
        _sa.Index("ix_geo_events_subject", "tenant_id", "subject_id", "occurred_at"),
        _sa.CheckConstraint("event IN ('enter', 'exit')", name="ck_geo_events_event"),
    )
