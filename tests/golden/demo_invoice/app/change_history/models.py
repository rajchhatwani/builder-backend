"""The change log: one row per audited field change (generated, append-only by convention)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Change(_models_base.Base):
    __tablename__ = "ch_changes"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    entity: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    record_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    field: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    # JSON text of the value; NULL = no value (a create has no old value, a delete no new one).
    # Longer than the cap in definitions.MAX_VALUE_BYTES: cut, ending in the marker.
    old_value: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    new_value: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    # the signed-in user who made the change; null when nobody was signed in
    actor_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    op: _orm.Mapped[str] = _orm.mapped_column(_sa.String(10), nullable=False)  # create | update | delete
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )

    __table_args__ = (
        _sa.Index("ix_ch_changes_record", "entity", "record_id", "created_at"),
        _sa.Index("ix_ch_changes_created_at", "created_at"),
    )
