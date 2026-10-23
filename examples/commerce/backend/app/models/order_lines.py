"""SQLAlchemy model for OrderLine (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.fulfillment_lines import FulfillmentLine
    from app.models.orders import Order
    from app.models.refund_lines import RefundLine
    from app.models.variants import Variant


class OrderLine(_models_base.Base):
    __tablename__ = "order_lines"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    variant_title: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    sku: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(100), nullable=True)
    quantity: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    unit_price: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    discount_total: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    tax_total: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('0'))
    fulfilled_quantity: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    refunded_quantity: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    properties: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    order_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("variants.id", ondelete="SET NULL"), nullable=True, index=True)
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

    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='lines', foreign_keys="[OrderLine.order_id]")
    variant: _orm.Mapped["Variant"] = _orm.relationship('Variant', back_populates='order_lines', foreign_keys="[OrderLine.variant_id]")
    fulfillment_lines: _orm.Mapped[list["FulfillmentLine"]] = _orm.relationship('FulfillmentLine', back_populates='order_line', foreign_keys="[FulfillmentLine.order_line_id]", passive_deletes=True)
    refund_lines: _orm.Mapped[list["RefundLine"]] = _orm.relationship('RefundLine', back_populates='order_line', foreign_keys="[RefundLine.order_line_id]", passive_deletes=True)
