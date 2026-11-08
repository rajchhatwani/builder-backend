import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectObservability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """OpenTelemetry settings of one project (1:1 with projects).

    `settings` holds the rest of SpecObservability (service name, sampling, switches, lists).
    No endpoint or header is stored: those are environment variables of the generated project.
    """

    __tablename__ = "project_observability"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
