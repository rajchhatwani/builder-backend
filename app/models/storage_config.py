import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import DownloadMode, StorageBackend
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectStorageConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """File storage settings of one project (1:1 with projects).

    Kept when storage is switched off, so turning it on again restores everything. No bucket
    credential is ever stored here: they are environment variables of the generated project.
    The nested blocks mirror the spec models (SpecStorageRoles / SpecStorageSecurity).
    """

    __tablename__ = "project_storage_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    backend: Mapped[StorageBackend] = mapped_column(
        SAEnum(StorageBackend, name="storage_backend", native_enum=False, length=8),
        nullable=False,
        default=StorageBackend.s3,
    )
    bucket: Mapped[str] = mapped_column(String(63), nullable=False, default="")
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    key_prefix: Mapped[str] = mapped_column(String(100), nullable=False, default="uploads")
    allowed_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    max_file_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    user_quota_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploads_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    download_mode: Mapped[DownloadMode] = mapped_column(
        SAEnum(DownloadMode, name="download_mode", native_enum=False, length=10),
        nullable=False,
        default=DownloadMode.proxy,
    )
    allow_inline_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    roles: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    security: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
