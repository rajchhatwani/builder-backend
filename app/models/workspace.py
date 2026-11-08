"""Draft workspaces and their checkpoints (B3-4, architecture 6.4)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


class Workspace(UUIDPrimaryKeyMixin, Base):
    """A draft: spec branch pointer + git worktree + preview DB. Production is unreachable."""

    __tablename__ = "workspaces"
    __table_args__ = (Index("ix_workspaces_project", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Spec op-log sequence the draft forked from, and where its spec ref points now.
    base_spec_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    worktree_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preview_db_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class WorkspaceCheckpoint(UUIDPrimaryKeyMixin, Base):
    """Code (git sha + tag), spec ref and data (snapshot database) at one moment."""

    __tablename__ = "workspace_checkpoints"
    __table_args__ = (Index("ix_ws_checkpoints_ws", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    git_tag: Mapped[str] = mapped_column(String(100), nullable=False)
    spec_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    db_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
