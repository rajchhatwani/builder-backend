"""The outbox and the consumer ledger (generated)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

PENDING = "pending"
DELIVERED = "delivered"
FAILED = "failed"


class OutboxEvent(_models_base.Base):
    """One event, written in the same transaction as the change that caused it."""

    __tablename__ = "ev_outbox"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    aggregate_type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    aggregate_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    # 1, 2, 3 ... per aggregate: an event is delivered only after every lower seq of its aggregate
    seq: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    event_type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    payload: _orm.Mapped[dict[str, object]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    # pending -> delivered, or pending -> failed (dead letter: kept, visible, never retried by itself)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False, default=PENDING)
    delivered_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    next_attempt_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    # error class and consumer names only: never a payload value
    last_error: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(500), nullable=True)

    __table_args__ = (
        _sa.UniqueConstraint("aggregate_type", "aggregate_id", "seq", name="uq_ev_outbox_aggregate_seq"),
        # the relay's claim query and the dead-letter view
        _sa.Index("ix_ev_outbox_claim", "status", "next_attempt_at"),
        # the purge
        _sa.Index("ix_ev_outbox_delivered_at", "delivered_at"),
    )


class HandledEvent(_models_base.Base):
    """Which consumer already handled which event (see outbox.already_handled)."""

    __tablename__ = "ev_handled"

    event_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    consumer: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), primary_key=True)
    handled_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (_sa.Index("ix_ev_handled_handled_at", "handled_at"),)
