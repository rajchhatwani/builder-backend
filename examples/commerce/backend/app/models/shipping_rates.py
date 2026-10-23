"""SQLAlchemy model for ShippingRate (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.orders import Order
    from app.models.shipping_zones import ShippingZone


class ShippingRate(_models_base.Base):
    __tablename__ = "shipping_rates"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    price: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    min_order_subtotal: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True)
    min_weight: _orm.Mapped[float | None] = _orm.mapped_column(_sa.Float(), nullable=True)
    max_weight: _orm.Mapped[float | None] = _orm.mapped_column(_sa.Float(), nullable=True)
    active: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    zone_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("shipping_zones.id", ondelete="CASCADE"), nullable=False, index=True)
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

    zone: _orm.Mapped["ShippingZone"] = _orm.relationship('ShippingZone', back_populates='rates', foreign_keys="[ShippingRate.zone_id]")
    orders: _orm.Mapped[list["Order"]] = _orm.relationship('Order', back_populates='shipping_rate', foreign_keys="[Order.shipping_rate_id]", passive_deletes=True)
