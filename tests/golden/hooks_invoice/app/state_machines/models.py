"""The state log: one row per state an entity record entered (generated, append-only by convention)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class StateTransition(_models_base.Base):
    __tablename__ = "state_transitions"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    entity: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    record_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    # "created" for the first state of a record, else the transition's name
    transition: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    from_state: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    to_state: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    # the signed-in user who caused it; null for the platform's own automatic moves
    actor_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    automatic: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (
        _sa.Index("ix_state_transitions_record", "entity", "record_id", "created_at"),
    )
