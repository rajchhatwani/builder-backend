"""SQLAlchemy model for Cart (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.cart_lines import CartLine
    from app.models.customers import Customer
    from app.models.orders import Order


class Cart(_models_base.Base):
    __tablename__ = "carts"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    token: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, unique=True)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(254), nullable=True)
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False, default='USD')
    status: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='open')
    discount_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    note: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    attributes: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    expires_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    customer_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
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

    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='carts', foreign_keys="[Cart.customer_id]")
    lines: _orm.Mapped[list["CartLine"]] = _orm.relationship('CartLine', back_populates='cart', foreign_keys="[CartLine.cart_id]", passive_deletes=True)
    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='cart', foreign_keys="[Order.cart_id]", passive_deletes=True, uselist=False)
