"""Realtime gateway storage (B4-2, C18): the project event log the SSE stream replays from."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import _utcnow


class RealtimeEvent(Base):
    """`id` (BIGSERIAL) is the event id and the resume cursor. Ids are global, so one project's ids
    have gaps; per project they are committed in id order (publish takes a per-project lock)."""

    __tablename__ = "realtime_events"
    __table_args__ = (
        Index("ix_realtime_events_project_id", "project_id", "id"),
        Index("ix_realtime_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(60), nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class RealtimeFloor(Base):
    """The highest event id pruned for a project: a cursor below it cannot be replayed exactly."""

    __tablename__ = "realtime_floors"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    floor_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
