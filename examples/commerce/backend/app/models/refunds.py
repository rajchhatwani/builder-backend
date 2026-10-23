"""SQLAlchemy model for Refund (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.orders import Order
    from app.models.refund_lines import RefundLine


class Refund(_models_base.Base):
    __tablename__ = "refunds"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    amount: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    reason: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(255), nullable=True)
    restock: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    note: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
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

    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='refunds', foreign_keys="[Refund.order_id]")
    lines: _orm.Mapped[list["RefundLine"]] = _orm.relationship('RefundLine', back_populates='refund', foreign_keys="[RefundLine.refund_id]", passive_deletes=True)
