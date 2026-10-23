"""SQLAlchemy model for DiscountUsage (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.discounts import Discount
    from app.models.orders import Order


class DiscountUsage(_models_base.Base):
    __tablename__ = "discount_usages"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(254), nullable=True)
    discount_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("discounts.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
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

    discount: _orm.Mapped["Discount"] = _orm.relationship('Discount', back_populates='usages', foreign_keys="[DiscountUsage.discount_id]")
    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='discount_usages', foreign_keys="[DiscountUsage.order_id]")
