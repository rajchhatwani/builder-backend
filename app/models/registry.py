"""Per-project registry: block versions, hooks ledger, dependency lock (B3-8)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


def _project_fk() -> ForeignKey:
    return ForeignKey("projects.id", ondelete="CASCADE")


class RegistryBlockVersion(UUIDPrimaryKeyMixin, Base):
    """A block at a version used by a project. (project, name, version) is immutable."""

    __tablename__ = "registry_block_versions"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (UniqueConstraint("project_id", "name", "version", name="uq_registry_block"),)


class RegistryHookEntry(UUIDPrimaryKeyMixin, Base):
    """Append-only: one row per hook body hash. Only `approved_by` may be set, once."""

    __tablename__ = "registry_hooks_ledger"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    hook_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("project_id", "hook_name", "content_hash", name="uq_registry_hook"),
        Index("ix_registry_hooks_project", "project_id", "hook_name"),
    )


class RegistryDepLock(UUIDPrimaryKeyMixin, Base):
    """Dependency lock entries; a (package, version) pair is immutable once recorded."""

    __tablename__ = "registry_deps_lock"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    package: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    hash: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (UniqueConstraint("project_id", "package", "version", name="uq_registry_dep"),)
