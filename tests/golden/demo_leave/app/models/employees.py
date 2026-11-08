"""SQLAlchemy model for Employee (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.leave_requests import LeaveRequest


class Employee(_models_base.Base):
    __tablename__ = "employees"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False, unique=True)
    department: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(60), nullable=True)
    leave_balance: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    leave_requests: _orm.Mapped[list["LeaveRequest"]] = _orm.relationship('LeaveRequest', back_populates='employee', foreign_keys="[LeaveRequest.employee_id]", passive_deletes=True)
