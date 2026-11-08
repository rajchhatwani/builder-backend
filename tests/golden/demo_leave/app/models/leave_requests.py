"""SQLAlchemy model for LeaveRequest (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.employees import Employee


class LeaveRequest(_models_base.Base):
    __tablename__ = "leave_requests"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    request_no: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False, unique=True)
    start_date: _orm.Mapped[_dt.date] = _orm.mapped_column(_sa.Date(), nullable=False)
    end_date: _orm.Mapped[_dt.date] = _orm.mapped_column(_sa.Date(), nullable=False)
    days: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    balance: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    state: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    employee_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    employee: _orm.Mapped["Employee"] = _orm.relationship('Employee', back_populates='leave_requests', foreign_keys="[LeaveRequest.employee_id]")
