"""SQLAlchemy model for Invoice (generated)."""
import datetime as _dt
import decimal as _decimal
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Invoice(_models_base.Base):
    __tablename__ = "invoices"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    invoice_no: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    po_amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )
