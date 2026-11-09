"""SQLAlchemy model for Expense (generated)."""
import datetime as _dt
import decimal as _decimal
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Expense(_models_base.Base):
    __tablename__ = "expenses"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    category: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    qty: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    rate: _orm.Mapped[float | None] = _orm.mapped_column(_sa.Float(), nullable=True)
    paid: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True)
    cost_basis: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True)
    spent_on: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True)
    logged_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(20), nullable=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default='draft')
    created_by_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )
