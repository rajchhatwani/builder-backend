"""Usage metering tables (B4-5): events (audit trail), counters (the atomic quota), limits."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


class UsageEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_org", "organization_id", "created_at"),
        # one granted event per (org, metric, key): the same key twice counts once
        Index(
            "uq_usage_events_idem",
            "organization_id",
            "metric",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND outcome = 'granted'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)  # granted | refused
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric: Mapped[str] = mapped_column(String(50), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class UsageLimit(Base):
    __tablename__ = "usage_limits"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric: Mapped[str] = mapped_column(String(50), primary_key=True)
    limit_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # None = unlimited
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
