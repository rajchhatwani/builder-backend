"""SQLAlchemy model for Variant (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.cart_lines import CartLine
    from app.models.inventory_levels import InventoryLevel
    from app.models.order_lines import OrderLine
    from app.models.products import Product


class Variant(_models_base.Base):
    __tablename__ = "variants"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False, default='Default')
    sku: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(100), nullable=True, unique=True)
    barcode: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, index=True)
    price: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    compare_at_price: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True)
    cost: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True)
    weight: _orm.Mapped[float | None] = _orm.mapped_column(_sa.Float(), nullable=True)
    position: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=1)
    option1: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    option2: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    option3: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    taxable: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    requires_shipping: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    inventory_policy: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='deny')
    inventory_tracked: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    product_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
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

    product: _orm.Mapped["Product"] = _orm.relationship('Product', back_populates='variants', foreign_keys="[Variant.product_id]")
    cart_lines: _orm.Mapped[list["CartLine"]] = _orm.relationship('CartLine', back_populates='variant', foreign_keys="[CartLine.variant_id]", passive_deletes=True)
    inventory_levels: _orm.Mapped[list["InventoryLevel"]] = _orm.relationship('InventoryLevel', back_populates='variant', foreign_keys="[InventoryLevel.variant_id]", passive_deletes=True)
    order_lines: _orm.Mapped[list["OrderLine"]] = _orm.relationship('OrderLine', back_populates='variant', foreign_keys="[OrderLine.variant_id]", passive_deletes=True)
