"""SQLAlchemy model for Employee (generated)."""
import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Employee(_models_base.Base):
    __tablename__ = "employees"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    salary: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    notes: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default='draft')
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
