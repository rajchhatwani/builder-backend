import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


class SpecOp(UUIDPrimaryKeyMixin, Base):
    """One entry of a project's append-only spec op-log (architecture section 3).

    Every builder-side change to the spec is one row: what was done (`op_type` + `payload`),
    how to take it back (`inverse`), who did it and the canonical hash of the spec on both
    sides. Rows are never updated or deleted (they go with the project). `seq` is dense and
    monotonic per project; writers serialise on the project row, so it never repeats.
    """

    __tablename__ = "spec_ops"
    __table_args__ = (
        UniqueConstraint("project_id", "seq", name="uq_spec_ops_project_seq"),
        Index("ix_spec_ops_project_seq", "project_id", "seq"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # user = a signed-in person (session or API token), mcp = the MCP server, system = no person.
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    op_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # do | undo | redo | restore; `ref_seq` names the entry an undo/redo/restore refers to.
    origin: Mapped[str] = mapped_column(String(10), nullable=False, default="do")
    ref_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    inverse: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    spec_hash_before: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_hash_after: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
