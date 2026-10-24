import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Authorization model and ABAC / PBAC policies of one project (1:1 with projects).

    `policies` is a list of SpecPolicy dicts and `attachments` maps "*" or a role name to policy
    ids (pbac only); both mirror the spec models. `version` counts saves, so a client can tell
    that someone else changed the policies while it was editing.
    """

    __tablename__ = "project_authorizations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    model: Mapped[str] = mapped_column(String(8), nullable=False, default="rbac")
    policies: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    attachments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
