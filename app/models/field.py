import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import FieldType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Field(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fields"
    __table_args__ = (UniqueConstraint("entity_id", "name", name="uq_fields_entity_name"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[FieldType] = mapped_column(
        SAEnum(FieldType, name="field_type", native_enum=False, length=20), nullable=False
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    enum_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
