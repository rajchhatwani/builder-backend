"""Metrics layer (B4-4, C22): named versioned definitions, reports over them, stored report runs."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


def _project_fk() -> ForeignKey:
    return ForeignKey("projects.id", ondelete="CASCADE")


class Metric(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "metrics"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_metrics_project_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class Report(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    schedule: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ReportRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "report_runs"
    __table_args__ = (
        UniqueConstraint("report_id", "scheduled_for", name="uq_report_runs_slot"),
        Index("ix_report_runs_project", "project_id"),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
