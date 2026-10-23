import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import KeycloakMode, MfaMode
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectKeycloakConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Keycloak settings of one project (1:1 with projects).

    The row is kept when the project switches back to built-in auth, so turning Keycloak on
    again restores everything. Which provider is active lives on ProjectAuthConfig.provider.
    Client secrets are never stored: they are environment variables of the generated project.
    """

    __tablename__ = "project_keycloak_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mode: Mapped[KeycloakMode] = mapped_column(
        SAEnum(KeycloakMode, name="keycloak_mode", native_enum=False, length=10),
        nullable=False,
        default=KeycloakMode.own,
    )
    realm: Mapped[str] = mapped_column(String(63), nullable=False)
    api_client_id: Mapped[str] = mapped_column(String(100), nullable=False)
    web_client_id: Mapped[str] = mapped_column(String(100), nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    password_min_length: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    mfa: Mapped[MfaMode] = mapped_column(
        SAEnum(MfaMode, name="keycloak_mfa", native_enum=False, length=10),
        nullable=False,
        default=MfaMode.optional,
    )
    session_idle_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    session_max_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    audit_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    identity_providers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Shared mode only: the builder project whose Keycloak this one trusts. Used to refuse
    # switching that project's Keycloak off while others depend on it; not part of the spec.
    source_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
