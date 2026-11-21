"""The job queue tables (generated)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
DEAD = "dead"


class Job(_models_base.Base):
    """One unit of background work. pending -> running -> succeeded, or back to pending (retry), or dead."""

    __tablename__ = "jb_jobs"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    queue: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    payload: _orm.Mapped[dict[str, object]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False, default=PENDING)
    # runs started so far (a claim counts, including one whose worker then died)
    attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    max_attempts: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    run_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    # the lease: only the holder of this token may finish the job; after lease_expires_at anyone may claim it
    lease_token: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    lease_expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
    locked_by: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(80), nullable=True)
    dedupe_key: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    # who the job belongs to, for dedupe_key scoping only (a multi-tenant project passes it to enqueue)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    # error class and a short message only: never a payload value
    last_error: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(300), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    finished_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # A dedupe_key is unique per tenant; a job without a tenant (single-tenant project, schedules)
        # is unique among the tenant-less ones.
        _sa.Index(
            "uq_jb_jobs_dedupe_key", "dedupe_key", unique=True, postgresql_where=_sa.text("tenant_id IS NULL")
        ),
        _sa.Index(
            "uq_jb_jobs_tenant_dedupe_key",
            "tenant_id",
            "dedupe_key",
            unique=True,
            postgresql_where=_sa.text("tenant_id IS NOT NULL"),
        ),
        _sa.Index("ix_jb_jobs_claim", "queue", "status", "run_at"),
        _sa.Index("ix_jb_jobs_finished_at", "finished_at"),
    )


class Schedule(_models_base.Base):
    """The first moment a schedule was seen: ticks before it are not 'missed', they never applied."""

    __tablename__ = "jb_schedules"

    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    baseline_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )


class ScheduleFire(_models_base.Base):
    """One tick of one schedule. The primary key makes 'fire once' a database fact: of any number of
    schedulers inserting the same (schedule, fire_time), exactly one succeeds, and only that one enqueues."""

    __tablename__ = "jb_schedule_fires"

    schedule: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    fire_time: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), primary_key=True)
    outcome: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)  # enqueued | skipped
    job_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
