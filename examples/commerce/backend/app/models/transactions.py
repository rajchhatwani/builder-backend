"""SQLAlchemy model for Transaction (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.orders import Order


class Transaction(_models_base.Base):
    __tablename__ = "transactions"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    kind: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False)
    gateway: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(60), nullable=True)
    reference: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True, index=True)
    error_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(60), nullable=True)
    processed_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    order_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
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

    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='transactions', foreign_keys="[Transaction.order_id]")
