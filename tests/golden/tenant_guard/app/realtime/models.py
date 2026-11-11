"""The realtime event log (generated). A row names a record and what happened to it; it never holds a
field value, so nothing hidden can leak through it. `created_by_id` and `tenant_id` are there only so the
stream can apply the same owner / tenant scope as the entity's list."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class RealtimeEvent(_models_base.Base):
    __tablename__ = "rt_events"

    id: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), primary_key=True, autoincrement=True)
    entity: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    record_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    op: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)  # created | updated | deleted
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_by_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (_sa.Index("ix_rt_events_created_at", "created_at"),)


class RealtimeFloor(_models_base.Base):
    """One row (id 1): the highest event id ever pruned. A cursor below it cannot be replayed exactly."""

    __tablename__ = "rt_floor"

    id: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), primary_key=True, autoincrement=False)
    floor_id: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
