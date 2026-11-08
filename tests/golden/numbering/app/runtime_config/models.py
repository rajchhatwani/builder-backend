"""Tables of the runtime configuration (generated): setting values, sequence counters, list items.

`tenant_id` is the caller's tenant in a multi-tenant project and the all-zero UUID otherwise, so the
primary keys never contain NULL."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class RcSetting(_models_base.Base):
    __tablename__ = "rc_settings"

    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), primary_key=True)
    value: _orm.Mapped[object] = _orm.mapped_column(_sa.JSON(), nullable=False)
    updated_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )


class RcSequence(_models_base.Base):
    """One counter row per sequence, tenant and period (the year, or 0 when it never resets).
    `next_value` is the number the next caller gets; it moves only inside that caller's transaction."""

    __tablename__ = "rc_sequences"

    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), primary_key=True)
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    period: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), primary_key=True)
    next_value: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)


class RcListItem(_models_base.Base):
    """A tenant's own entry of a list: a new value, or an override of a system value."""

    __tablename__ = "rc_list_items"

    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    list_name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), primary_key=True)
    value: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    label: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    color: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(7), nullable=True)
    position: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    active: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False)
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
