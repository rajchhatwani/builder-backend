import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectBehavior(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Declarative behaviour of one project (1:1 with projects): state machines now, later
    settings, history, hooks and seed plans. `sections` maps a section name to its JSON, shaped
    like the matching part of the spec; shapes are checked by the spec models on every read."""

    __tablename__ = "project_behavior"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
