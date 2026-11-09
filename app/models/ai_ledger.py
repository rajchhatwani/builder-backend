"""AI usage: the per-org settings (BYO key, budget) and the append-only cost ledger (B3-7)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, _utcnow


class AiOrgSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_org_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Fernet token (app.core.crypto). The plaintext key is never stored or returned.
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)  # last 4 chars
    monthly_budget_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # B-001: this org's approval policy override. It can only TIGHTEN the platform policy
    # (shorter lifetimes, higher role floors, auto-approval off, separation of duties on).
    approval_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AiCostLedger(UUIDPrimaryKeyMixin, Base):
    """One row per model call. Never updated; rows go only with the org."""

    __tablename__ = "ai_cost_ledger"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    task_class: Mapped[str] = mapped_column(String(30), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # B-009: "run_id:seq" of the agent step this call belongs to; a retry never bills twice.
    step_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_ai_cost_ledger_org_created", "organization_id", "created_at"),
        Index(
            "uq_ai_cost_ledger_step_key",
            "step_key",
            unique=True,
            postgresql_where=text("step_key IS NOT NULL"),
        ),
    )


class AiPlatformBudget(Base):
    """Singleton row (id = 1): all-time real model spend + in-flight reservations, platform-wide."""

    __tablename__ = "ai_platform_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spent_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reserved_micro_usd: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    cap_override_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class AiSpendReservation(Base):
    """One in-flight worst-case spend reservation (platform cap or org budget) with an expiry.

    A process that dies between reserve and settle leaves a row behind; the reaper deletes expired
    rows (and, for the platform scope, gives their amount back to the counter), so a crash can never
    shrink a cap for longer than the TTL.
    """

    __tablename__ = "ai_spend_reservations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)  # "platform" | "org"
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ai_spend_reservations_expires", "expires_at"),
        Index("ix_ai_spend_reservations_org", "organization_id"),
    )
