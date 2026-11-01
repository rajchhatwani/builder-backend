"""The workflow tables (generated)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

PENDING = "pending"
RUNNING = "running"
COMPENSATING = "compensating"
SUCCEEDED = "succeeded"
FAILED = "failed"
COMPENSATED = "compensated"
COMPENSATION_FAILED = "compensation_failed"
CANCELLED = "cancelled"
ACTIVE = (PENDING, RUNNING, COMPENSATING)
FINISHED = (SUCCEEDED, FAILED, COMPENSATED, COMPENSATION_FAILED, CANCELLED)

FORWARD = "forward"
COMPENSATE = "compensate"


class Run(_models_base.Base):
    """One execution of a workflow. `cursor` is the index of the next step to run (status pending / running)
    or of the next step to undo, counting down (status compensating); -1 means nothing left to undo."""

    __tablename__ = "wf_runs"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    workflow: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(24), nullable=False, default=PENDING)
    input: _orm.Mapped[dict[str, object]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    cursor: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    # runs started on the cursor's step (a start counts, including one whose worker then died)
    attempt: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    # why the run is compensating, and so how it ends: failure -> compensated, cancel -> cancelled
    reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(16), nullable=True)
    cancel_requested: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=False)
    next_run_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    deadline_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    lease_token: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    lease_expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    locked_by: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(80), nullable=True)
    dedupe_key: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    # error class and the failing step only: never an input or result value
    error: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(300), nullable=True)
    failed_step: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(40), nullable=True)
    created_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    finished_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        _sa.Index(
            "uq_wf_runs_dedupe_key",
            "workflow",
            "dedupe_key",
            unique=True,
            postgresql_where=_sa.text("tenant_id IS NULL AND dedupe_key IS NOT NULL"),
        ),
        _sa.Index(
            "uq_wf_runs_tenant_dedupe_key",
            "tenant_id",
            "workflow",
            "dedupe_key",
            unique=True,
            postgresql_where=_sa.text("tenant_id IS NOT NULL AND dedupe_key IS NOT NULL"),
        ),
        _sa.Index("ix_wf_runs_claim", "status", "next_run_at"),
        _sa.Index("ix_wf_runs_tenant", "tenant_id", "workflow", "created_at"),
        _sa.Index("ix_wf_runs_finished_at", "finished_at"),
    )


class StepRecord(_models_base.Base):
    """A step that reached its end in one phase. The primary key makes 'record once' a database fact: a step
    that is recorded is never executed again, however many workers race for the run."""

    __tablename__ = "wf_steps"

    run_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), _sa.ForeignKey("wf_runs.id", ondelete="CASCADE"), primary_key=True
    )
    step: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    phase: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), primary_key=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)  # succeeded | failed
    attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    result: _orm.Mapped[object | None] = _orm.mapped_column(_sa.JSON(), nullable=True)
    idempotency_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    error: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(300), nullable=True)
    finished_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
