import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.validation import AUTH_USER_COLUMNS
from app.models.base import Base
from app.models.enums import AuthCustomFieldType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# Field names that are reserved by the generated User model and must not be
# used as custom field names. Enforced in validation.
RESERVED_USER_FIELD_NAMES: frozenset[str] = AUTH_USER_COLUMNS | frozenset(
    # Not columns today, but kept off-limits so a later release can add them.
    {"is_verified", "role", "tenant_id"}
)


class AuthCustomField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An additional column on the generated project's `users` table.

    Each row becomes:
    - A real Postgres column (via the generated Alembic migration).
    - A validated Pydantic field on `UserCreate` / `UserUpdate` schemas.
    - A filterable / sortable field on `GET /admin/users` if `indexed=True`.

    `min_length` / `max_length` apply to string-like types.
    `min_value` / `max_value` apply to numeric types.
    `enum_values` is a JSON array of allowed strings (only for type='enum').
    `default_value` is stored as TEXT and cast to the correct Python type at
    generation time (strings are already the right type; numerics are parsed).

    Validation enforces type/constraint coherence (e.g. enum_values required
    for type='enum', max_length ignored for type='integer').
    """

    __tablename__ = "auth_custom_fields"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_auth_custom_fields_project_name"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[AuthCustomFieldType] = mapped_column(
        SAEnum(
            AuthCustomFieldType,
            name="auth_custom_field_type",
            native_enum=False,
            length=15,
        ),
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # String-type constraints
    min_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Numeric constraints
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Stored as TEXT; generator casts to the field's Python type
    default_value: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Only for type='enum'
    enum_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Extra JSON for future extensibility (e.g. regex pattern, placeholder text)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Determines column order in the generated migration and schema
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
