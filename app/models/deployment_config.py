import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectDeployment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cloud deployment settings of one project (1:1 with projects).

    Holds no credential of any kind: pipelines sign in to the cloud with short-lived OIDC tokens.
    `environments` is a list of SpecDeployEnvironment dicts.
    """

    __tablename__ = "project_deployments"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cloud: Mapped[str] = mapped_column(String(8), nullable=False, default="aws")
    region: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    github_repo: Mapped[str] = mapped_column(String(140), nullable=False, default="")
    environments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
