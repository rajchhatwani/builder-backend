"""SQLAlchemy model for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.carts import Cart
    from app.models.customers import Customer
    from app.models.discount_usages import DiscountUsage
    from app.models.fulfillments import Fulfillment
    from app.models.order_events import OrderEvent
    from app.models.order_lines import OrderLine
    from app.models.refunds import Refund
    from app.models.shipping_rates import ShippingRate
    from app.models.transactions import Transaction


class Order(_models_base.Base):
    __tablename__ = "orders"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    number: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False, unique=True)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(254), nullable=True, index=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default='open')
    financial_status: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='pending')
    fulfillment_status: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='unfulfilled')
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False, default='USD')
    subtotal: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    shipping_total: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    tax_total: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    discount_total: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    total: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    total_refunded: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    billing_address: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    shipping_address: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    shipping_method: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    discount_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    note: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    tags_cache: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    source: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(60), nullable=True, default='web')
    placed_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    closed_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    cancelled_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    cancel_reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    cart_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("carts.id", ondelete="SET NULL"), nullable=True, unique=True)
    customer_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    shipping_rate_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("shipping_rates.id", ondelete="SET NULL"), nullable=True, index=True)
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

    cart: _orm.Mapped["Cart"] = _orm.relationship('Cart', back_populates='order', foreign_keys="[Order.cart_id]")
    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='orders', foreign_keys="[Order.customer_id]")
    shipping_rate: _orm.Mapped["ShippingRate"] = _orm.relationship('ShippingRate', back_populates='orders', foreign_keys="[Order.shipping_rate_id]")
    discount_usages: _orm.Mapped[list["DiscountUsage"]] = _orm.relationship('DiscountUsage', back_populates='order', foreign_keys="[DiscountUsage.order_id]", passive_deletes=True)
    events: _orm.Mapped[list["OrderEvent"]] = _orm.relationship('OrderEvent', back_populates='order', foreign_keys="[OrderEvent.order_id]", passive_deletes=True)
    fulfillments: _orm.Mapped[list["Fulfillment"]] = _orm.relationship('Fulfillment', back_populates='order', foreign_keys="[Fulfillment.order_id]", passive_deletes=True)
    lines: _orm.Mapped[list["OrderLine"]] = _orm.relationship('OrderLine', back_populates='order', foreign_keys="[OrderLine.order_id]", passive_deletes=True)
    refunds: _orm.Mapped[list["Refund"]] = _orm.relationship('Refund', back_populates='order', foreign_keys="[Refund.order_id]", passive_deletes=True)
    transactions: _orm.Mapped[list["Transaction"]] = _orm.relationship('Transaction', back_populates='order', foreign_keys="[Transaction.order_id]", passive_deletes=True)
