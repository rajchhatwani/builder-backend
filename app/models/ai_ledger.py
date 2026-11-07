"""AI usage: the per-org settings (BYO key, budget) and the append-only cost ledger (B3-7)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_ai_cost_ledger_org_created", "organization_id", "created_at"),)


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
