"""Requirements map of a project: typed items, clarifying questions, sources (B3-6; arch 6.8)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow

KINDS = (
    "actor",
    "entity",
    "workflow",
    "rule",
    "integration",
    "compliance",
    "nonfunctional",
    "out_of_scope",
)
ITEM_STATES = ("open", "covered", "out_of_scope")


def _project_fk() -> ForeignKey:
    return ForeignKey("projects.id", ondelete="CASCADE")


class RequirementsMap(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "requirements_maps"
    __table_args__ = (Index("uq_requirements_maps_project", "project_id", unique=True),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # [{name, kind, pages, chunks, chars}] of every document read so far
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class RequirementItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "requirement_items"
    __table_args__ = (Index("ix_requirement_items_map", "map_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    map_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements_maps.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(String(600), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_doc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    covered_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class RequirementQuestion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "requirement_questions"
    __table_args__ = (Index("ix_requirement_questions_map", "map_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    map_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements_maps.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(600), nullable=False)
    assumption: Mapped[str] = mapped_column(String(600), nullable=False)
    answer: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="open")  # open|answered|assumed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
