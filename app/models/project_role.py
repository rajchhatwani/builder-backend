import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A role defined for a generated project's RBAC system.

    Role names must be unique per project and follow the identifier rules
    (lower-snake_case, no SQL/Python reserved words) enforced by validation.

    `inherits_from` is a role name (not id) within the same project, allowing
    a simple one-level hierarchy (admin inherits all editor permissions etc.).
    Multi-level chains are not supported in Phase 2.
    """

    __tablename__ = "project_roles"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_roles_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)

    # Exactly one role per project must have is_default=True.
    # Enforced by application logic (not DB constraint) to produce a clear error.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # If True, end-users may select this role for themselves at registration.
    self_assignable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # If True, a user can only receive this role via an admin invitation link.
    invite_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Name of another role in the same project whose permissions this role inherits.
    inherits_from: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Display order in the dashboard / generated admin UI.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
