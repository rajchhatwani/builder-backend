"""Payment tables (generated). They are created by alembic/versions/0003_payments.py.

No card data is stored anywhere: only our ids, provider references, statuses and amounts.
"""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.models._base import Base, utcnow


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), nullable=False, default=utcnow)


def _updated() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Payment(Base):
    __tablename__ = "pay_payments"
    __table_args__ = (
        sa.CheckConstraint("amount_minor > 0", name="ck_pay_payments_amount_positive"),
        sa.CheckConstraint(
            "refunded_minor >= 0 AND refunded_minor <= refund_reserved_minor "
            "AND refund_reserved_minor <= amount_minor",
            name="ck_pay_payments_refund_bounds",
        ),
        sa.Index(
            "uq_pay_payments_active_payable",
            "payable_id",
            unique=True,
            postgresql_where=sa.text(
                "status IN ('creating', 'requires_payment', 'processing', 'succeeded')"
            ),
        ),
        sa.Index("ix_pay_payments_tenant_created", "tenant_id", "created_at"),
        sa.Index("ix_pay_payments_creator_created", "created_by_id", "created_at"),
        sa.Index("ix_pay_payments_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    livemode: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    payable_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), nullable=False)
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    refunded_minor: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False, default=0)
    refund_reserved_minor: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False, default=0)
    provider_session_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, unique=True
    )
    provider_payment_intent_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, index=True
    )
    checkout_url: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # Exact allowlisted URLs chosen at creation; kept so a retry can finish the checkout.
    success_url: Mapped[str] = mapped_column(sa.String(2000), nullable=False)
    cancel_url: Mapped[str] = mapped_column(sa.String(2000), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Refund(Base):
    __tablename__ = "pay_refunds"
    __table_args__ = (
        sa.CheckConstraint("amount_minor > 0", name="ck_pay_refunds_amount_positive"),
        # The two-person rule is enforced by the database too, not only by the service.
        sa.CheckConstraint(
            "approved_by_id IS NULL OR requested_by_id IS NULL OR approved_by_id <> requested_by_id",
            name="ck_pay_refunds_two_people",
        ),
        sa.Index("ix_pay_refunds_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("pay_payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    reason: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(10), nullable=False)  # api | provider
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    provider_refund_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, unique=True
    )
    failure_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Dispute(Base):
    __tablename__ = "pay_disputes"

    id: Mapped[uuid.UUID] = _pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("pay_payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    provider_dispute_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    evidence_due_by: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class WebhookEvent(Base):
    __tablename__ = "pay_webhook_events"
    __table_args__ = (
        sa.UniqueConstraint("provider", "event_id", name="uq_pay_webhook_events_provider_event"),
        sa.Index("ix_pay_webhook_events_status_received", "status", "received_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    event_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    livemode: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    attempts: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    # Reduced: ids, types, statuses, amounts. No names, emails, addresses or card details.
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB(), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provider_created_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "pay_idempotency_keys"

    id: Mapped[uuid.UUID] = _pk()
    # sha256 of tenant, user, route and the client's key: the key itself is never stored
    scope_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )


class Job(Base):
    __tablename__ = "pay_jobs"
    __table_args__ = (sa.Index("ix_pay_jobs_status_run_at", "status", "run_at"),)

    id: Mapped[uuid.UUID] = _pk()
    type: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB(), nullable=False)  # ids only
    status: Mapped[str] = mapped_column(sa.String(10), nullable=False)  # queued|running|done|dead
    run_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    attempts: Mapped[int] = mapped_column(sa.Integer(), nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    locked_by: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True, unique=True)
    last_error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AuditLog(Base):
    """Append-only; the database refuses UPDATE and TRUNCATE, and DELETE outside the purge tool.

    Each row's hash covers the previous row of the same chain (one chain per payment, one for
    system events), so an edited or removed row breaks every hash after it.
    """

    __tablename__ = "pay_audit_log"
    __table_args__ = (sa.UniqueConstraint("chain_key", "seq", name="uq_pay_audit_log_chain_seq"),)

    id: Mapped[uuid.UUID] = _pk()
    chain_key: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(sa.String(10), nullable=False)  # user|system|provider
    actor_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), nullable=True)
    event: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB(), nullable=False)
    prev_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)


class PaymentsLock(Base):
    """Which provider and mode (test or live) this database holds payments for."""

    __tablename__ = "pay_lock"

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    provider: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    livemode: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    created_at: Mapped[datetime] = _created()
