import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AuthOperation, RowRule
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectPermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Maps an (entity, operation) pair to a set of roles and an optional row rule.

    One row = one (entity × operation) slot. The `roles` column is a Postgres
    TEXT[] array, which is the natural fit for an ordered, searchable list of
    role names without a junction table overhead.

    `custom_filter_field` and `custom_filter_value` are only meaningful when
    `row_rule = 'custom_filter'`. The generator will emit:
        WHERE <custom_filter_field> = '<custom_filter_value>'
    injected into the entity's list/get queries for the affected roles.

    Validation ensures:
    - entity_id belongs to this project
    - (entity_id, operation) is unique per project
    - all role names exist in project_roles for this project
    - custom_filter fields are populated iff row_rule = 'custom_filter'
    """

    __tablename__ = "project_permissions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "entity_id",
            "operation",
            name="uq_project_permissions_project_entity_op",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[AuthOperation] = mapped_column(
        SAEnum(AuthOperation, name="auth_operation", native_enum=False, length=15),
        nullable=False,
    )
    # Postgres TEXT[] — list of role names allowed to call this endpoint.
    # An empty array means the operation is publicly accessible (no auth required).
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False)

    row_rule: Mapped[RowRule | None] = mapped_column(
        SAEnum(RowRule, name="row_rule", native_enum=False, length=20),
        nullable=True,
    )
    # Only used when row_rule = 'custom_filter'
    custom_filter_field: Mapped[str | None] = mapped_column(String(100), nullable=True)
    custom_filter_value: Mapped[str | None] = mapped_column(Text, nullable=True)
