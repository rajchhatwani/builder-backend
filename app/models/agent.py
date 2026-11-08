"""Builder agent run model and approvals (B3-1, B3-5; architecture 6.1, 6.5)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow


def _project_fk() -> ForeignKey:
    return ForeignKey("projects.id", ondelete="CASCADE")


class AiRun(UUIDPrimaryKeyMixin, Base):
    """One agent run. State lives here, not in memory, so a crashed run resumes from its steps."""

    __tablename__ = "ai_runs"
    __table_args__ = (
        Index("ix_ai_runs_project", "project_id", "created_at"),
        # S1-014: the workspace-busy guard filters (workspace_id, state)
        Index("ix_ai_runs_workspace_state", "workspace_id", "state"),
        # S1-006: one live run per workspace (two would overwrite each other's files)
        Index(
            "uq_ai_runs_live_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text(
                "workspace_id IS NOT NULL AND state IN "
                "('created','planning','awaiting_approval','running','gating','applying')"
            ),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    # created | planning | awaiting_approval | running | gating | applying | applied | stopped | failed | cancelled
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    phase: Mapped[str] = mapped_column(String(10), nullable=False, default="plan")
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    budgets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    steps_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repairs_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Active driving time over the whole run (B-008): approvals and resumes cannot reset it.
    wall_ms_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    stop_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stop_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Resumability: one driver holds the lease; an expired lease means the driver died.
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AiStep(UUIDPrimaryKeyMixin, Base):
    """Append-only record of one model call, tool call, gate run or approval wait."""

    __tablename__ = "ai_steps"
    __table_args__ = (
        Index("uq_ai_steps_run_seq", "run_id", "seq", unique=True),
        Index(
            "uq_ai_steps_run_call",
            "run_id",
            "tool_call_id",
            unique=True,
            postgresql_where="tool_call_id IS NOT NULL",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # model|tool|gate|approval|system
    tool_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # idempotency
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="done")  # pending|done
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_set_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AiApproval(UUIDPrimaryKeyMixin, Base):
    """A human decision (kinds A-E), bound to a spec hash and a commit, expiring."""

    __tablename__ = "ai_approvals"
    __table_args__ = (
        Index("ix_ai_approvals_run", "run_id", "created_at"),
        # S1-014: the inbox filters project_id (+ state) and orders by created_at
        Index("ix_ai_approvals_project_state", "project_id", "state", "created_at"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    kind: Mapped[str] = mapped_column(String(1), nullable=False)  # A-E
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # pending | approved | denied | expired | superseded
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    bound_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bound_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # sha256 of the canonical payload when it was asked / last edited by a decision. An approval is
    # only used while the payload still hashes to this (S1-004: a changed payload invalidates it).
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AiDraftOp(UUIDPrimaryKeyMixin, Base):
    """One spec operation of a run's private draft (H2). The live spec never sees these rows: they
    are folded over the run's base spec for the agent's reads and replayed onto the live project
    only when the final review (C) is approved; every other end of the run deletes them."""

    __tablename__ = "ai_draft_ops"
    __table_args__ = (Index("uq_ai_draft_ops_run_seq", "run_id", "seq", unique=True),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _project_fk(), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    op_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
