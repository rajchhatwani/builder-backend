"""SQLAlchemy model for Customer (generated)."""
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
    from app.models.customer_addresses import CustomerAddress
    from app.models.gift_cards import GiftCard
    from app.models.orders import Order
    from app.models.reviews import Review


class Customer(_models_base.Base):
    __tablename__ = "customers"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(254), nullable=True, index=True)
    first_name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(100), nullable=True)
    last_name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(100), nullable=True)
    phone: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(30), nullable=True)
    state: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='enabled')
    accepts_marketing: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    accepts_marketing_updated_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    tax_exempt: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    total_spent: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    orders_count: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    tags_cache: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    note: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    locale: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(10), nullable=True)
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
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    addresses: _orm.Mapped[list["CustomerAddress"]] = _orm.relationship('CustomerAddress', back_populates='customer', foreign_keys="[CustomerAddress.customer_id]", passive_deletes=True)
    carts: _orm.Mapped[list["Cart"]] = _orm.relationship('Cart', back_populates='customer', foreign_keys="[Cart.customer_id]", passive_deletes=True)
    gift_cards: _orm.Mapped[list["GiftCard"]] = _orm.relationship('GiftCard', back_populates='customer', foreign_keys="[GiftCard.customer_id]", passive_deletes=True)
    orders: _orm.Mapped[list["Order"]] = _orm.relationship('Order', back_populates='customer', foreign_keys="[Order.customer_id]", passive_deletes=True)
    reviews: _orm.Mapped[list["Review"]] = _orm.relationship('Review', back_populates='customer', foreign_keys="[Review.customer_id]", passive_deletes=True)
