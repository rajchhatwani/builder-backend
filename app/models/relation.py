import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import OnDelete, RelationKind
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Relation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "relations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "from_entity_id",
            "to_entity_id",
            "from_name",
            name="uq_relations_project_from_to_from_name",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[RelationKind] = mapped_column(
        SAEnum(RelationKind, name="relation_kind", native_enum=False, length=20), nullable=False
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    from_name: Mapped[str] = mapped_column(String(100), nullable=False)
    to_name: Mapped[str] = mapped_column(String(100), nullable=False)
    on_delete: Mapped[OnDelete] = mapped_column(
        SAEnum(OnDelete, name="on_delete", native_enum=False, length=20),
        nullable=False,
        default=OnDelete.restrict,
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
