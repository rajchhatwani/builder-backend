"""SQLAlchemy model for LeaveRequest (generated)."""
import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class LeaveRequest(_models_base.Base):
    __tablename__ = "leave_requests"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    employee: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    days: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    balance: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    state: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
