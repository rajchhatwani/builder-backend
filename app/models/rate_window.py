"""Shared fixed-window counters (FX-1): one row per (key, window). Platform infrastructure, not
tenant data, so it carries no organization link (listed in the RLS coverage allow-list)."""

from sqlalchemy import BigInteger, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RateWindow(Base):
    __tablename__ = "rate_windows"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # epoch seconds
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)  # epoch seconds

    __table_args__ = (Index("ix_rate_windows_expires", "expires_at"),)
