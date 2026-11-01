"""The webhook tables (generated). No secret is stored here: signing secrets live in the credential vault."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

ACTIVE = "active"
DISABLED = "disabled"
PENDING = "pending"
DELIVERED = "delivered"
FAILED = "failed"
CANCELLED = "cancelled"


class Subscription(_models_base.Base):
    """One receiver URL of one tenant and the event types it gets. The secret is in the vault under
    `out_<id>_v<secret_version>` (and `_v<previous_version>` while a rotation overlaps)."""

    __tablename__ = "wh_subscriptions"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    url: _orm.Mapped[str] = _orm.mapped_column(_sa.String(2048), nullable=False)
    description: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False, default="")
    event_types: _orm.Mapped[list[str]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False, default=ACTIVE)
    disabled_reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(40), nullable=True)
    consecutive_failures: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    secret_version: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=1)
    previous_version: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    previous_expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    created_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (_sa.Index("ix_wh_subscriptions_tenant", "tenant_id", "status"),)


class Delivery(_models_base.Base):
    """One event to one subscription. `id` is the idempotency id sent as `webhook-id` on every attempt;
    (subscription, event) is unique, so an event delivered twice by the bus creates one delivery."""

    __tablename__ = "wh_deliveries"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    subscription_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), _sa.ForeignKey("wh_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    event_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    event_type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    occurred_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    payload: _orm.Mapped[dict[str, object]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False, default=PENDING)
    attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    last_status_code: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    last_error: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(60), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    finished_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _sa.UniqueConstraint("subscription_id", "event_id", name="uq_wh_deliveries_subscription_event"),
        _sa.Index("ix_wh_deliveries_subscription", "subscription_id", "created_at"),
        _sa.Index("ix_wh_deliveries_finished_at", "finished_at"),
    )


class Attempt(_models_base.Base):
    """The delivery log: one row per try. Only codes and numbers, never a body, header or secret."""

    __tablename__ = "wh_attempts"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    delivery_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), _sa.ForeignKey("wh_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    attempt: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    outcome: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), nullable=False)
    status_code: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    duration_ms: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (_sa.Index("ix_wh_attempts_delivery", "delivery_id", "attempt"),)


class Endpoint(_models_base.Base):
    """The secret versions of one incoming endpoint of one tenant. Secrets are in the vault under
    `in_<endpoint>_v<version>`; the tenant is the nil UUID in a project that is not multi-tenant."""

    __tablename__ = "wh_endpoints"

    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    secret_version: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    previous_version: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    previous_expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )


class InboundSeen(_models_base.Base):
    """Delivery ids already accepted by an incoming endpoint (replay and duplicate defence)."""

    __tablename__ = "wh_inbound"

    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    endpoint: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    delivery_id: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), primary_key=True)
    received_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (_sa.Index("ix_wh_inbound_received_at", "received_at"),)
