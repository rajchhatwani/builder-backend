import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import DbEngine
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    db_engine: Mapped[DbEngine] = mapped_column(
        SAEnum(DbEngine, name="db_engine", native_enum=False, length=20),
        nullable=False,
        default=DbEngine.postgres,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Every project belongs to exactly one org (§3.2). RESTRICT: an org can't be deleted out
    # from under its projects.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (Index("ix_projects_org", "organization_id"),)
