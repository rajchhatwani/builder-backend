"""Booking tables (generated). Double booking is refused by an EXCLUDE constraint (see
alembic/versions/0037_booking.py); pool capacity is checked under a row lock on the resource."""

import datetime as _dt
import uuid as _uuid
from typing import Any as _Any

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


class BookingResource(_models_base.Base):
    __tablename__ = "booking_resources"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_booking_resources_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    kind: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    mode: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    timezone: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default="UTC", server_default="UTC")
    slot_minutes: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    schedule: _orm.Mapped[dict[str, _Any] | None] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    capacity: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=1, server_default="1")
    min_minutes: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    max_minutes: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    active: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=True, server_default=_sa.true())
    created_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (
        _sa.CheckConstraint("mode IN ('slot', 'range', 'pool')", name="ck_booking_resources_mode"),
        _sa.CheckConstraint("capacity >= 1", name="ck_booking_resources_capacity"),
    )


class Booking(_models_base.Base):
    __tablename__ = "bookings"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_bookings_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    resource_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("booking_resources.id", name="fk_bookings_resource_id_booking_resources"), nullable=False
    )
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(12), nullable=False, default="held", server_default="held")
    exclusive: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False)
    starts_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    ends_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    quantity: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=1, server_default="1")
    hold_expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    customer_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    customer_ref: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(128), nullable=True)
    notes: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(500), nullable=True)
    idempotency_key: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(128), nullable=True)
    request_hash: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    cancel_fee_minor: _orm.Mapped[int | None] = _orm.mapped_column(_sa.BigInteger(), nullable=True)
    fee_currency: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(3), nullable=True)
    cancel_reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _created()
    confirmed_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    cancelled_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    expired_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _sa.UniqueConstraint("tenant_id", "customer_id", "idempotency_key", name="uq_bookings_idempotency_key"),
        _sa.CheckConstraint("status IN ('held', 'confirmed', 'cancelled', 'expired')", name="ck_bookings_status"),
        _sa.CheckConstraint("ends_at > starts_at", name="ck_bookings_range"),
        _sa.CheckConstraint("quantity >= 1", name="ck_bookings_quantity"),
        _sa.CheckConstraint("cancel_fee_minor IS NULL OR cancel_fee_minor >= 0", name="ck_bookings_fee"),
        _sa.Index("ix_bookings_status_hold_expires_at", "status", "hold_expires_at"),
        _sa.Index("ix_bookings_resource_id_starts_at", "resource_id", "starts_at"),
    )
