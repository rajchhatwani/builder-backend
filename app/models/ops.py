"""Operator job heartbeats (CP-5V): one row per periodic job, written by the scheduler ticks."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import _utcnow


class JobHeartbeat(Base):
    __tablename__ = "job_heartbeats"

    job: Mapped[str] = mapped_column(String(60), primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_status: Mapped[str] = mapped_column(String(10), nullable=False)  # ok | failed
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)  # exception type only
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runs: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
