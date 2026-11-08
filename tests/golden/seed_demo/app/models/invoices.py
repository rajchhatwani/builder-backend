"""SQLAlchemy model for Invoice (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.customers import Customer


class Invoice(_models_base.Base):
    __tablename__ = "invoices"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    invoice_no: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False, unique=True)
    amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    issued_on: _orm.Mapped[_dt.date] = _orm.mapped_column(_sa.Date(), nullable=False)
    memo: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    customer_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", ondelete="RESTRICT"), nullable=True, index=True
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

    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='invoices', foreign_keys="[Invoice.customer_id]")
