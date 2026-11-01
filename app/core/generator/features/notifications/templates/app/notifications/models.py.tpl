"""Notification tables (generated): templates, preferences, delivery log."""

import datetime as _dt
import uuid as _uuid
from typing import Any

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

QUEUED = "queued"
PROCESSING = "processing"
SENT = "sent"
FAILED = "failed"
SUPPRESSED = "suppressed"
STATUSES = (QUEUED, PROCESSING, SENT, FAILED, SUPPRESSED)


class NotificationTemplate(_models_base.Base):
    """A tenant's override of one default template."""

    __tablename__ = "nt_templates"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    channel: _orm.Mapped[str] = _orm.mapped_column(_sa.String(10), nullable=False)
    subject: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False, default="")
    body: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    html: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=False)
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)

    __table_args__ = (_sa.UniqueConstraint("tenant_id", "type", "channel", name="uq_nt_templates_key"),)


class NotificationPreference(_models_base.Base):
    """One user's choice for one type and channel (absent = the type's default)."""

    __tablename__ = "nt_preferences"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    user_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    channel: _orm.Mapped[str] = _orm.mapped_column(_sa.String(10), nullable=False)
    enabled: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False)
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (
        _sa.UniqueConstraint("tenant_id", "user_key", "type", "channel", name="uq_nt_preferences_key"),
    )


class NotificationDelivery(_models_base.Base):
    """One message: the delivery log row and the queue entry in one. `address` and `variables` are
    needed to send and are cleared (NULL) as soon as the message is sent, suppressed or finally failed;
    the rendered body is never stored. `recipient_hint` is a masked address for humans."""

    __tablename__ = "nt_deliveries"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    channel: _orm.Mapped[str] = _orm.mapped_column(_sa.String(10), nullable=False)
    recipient_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    recipient_hint: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False, default="")
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(12), nullable=False)
    reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(40), nullable=True)
    attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    provider: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    provider_message_id: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    error_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(40), nullable=True)
    source_event_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    dedupe_key: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    address: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(600), nullable=True)
    variables: _orm.Mapped[dict[str, Any] | None] = _orm.mapped_column(_sa.JSON(), nullable=True)
    next_attempt_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    lease_token: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    lease_expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    finished_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _sa.Index("ix_nt_deliveries_due", "status", "next_attempt_at"),
        _sa.Index("ix_nt_deliveries_tenant", "tenant_id", "created_at"),
        _sa.Index(
            "uq_nt_deliveries_dedupe",
            "tenant_id",
            "dedupe_key",
            unique=True,
            postgresql_where=_sa.text("dedupe_key IS NOT NULL"),
        ),
    )
