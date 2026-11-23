"""Upgrade proposals (P3): what regenerating a project with the current generator would change."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


class UpgradeProposal(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "upgrade_proposals"
    __table_args__ = (
        Index("ix_upgrade_proposals_project_created", "project_id", "created_at"),
        # One open proposal per base generation, enforced by the database (a race cannot make two).
        Index(
            "uq_upgrade_proposals_open",
            "project_id",
            "base_generation_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    base_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")  # open|applied|dismissed
    from_generator_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    block_changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    patch_text: Mapped[str] = mapped_column(Text, nullable=False)
    sbom_diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    migrations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    scorecard: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    auto_apply_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
