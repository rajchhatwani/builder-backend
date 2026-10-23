"""SQLAlchemy model for RefundLine (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.order_lines import OrderLine
    from app.models.refunds import Refund


class RefundLine(_models_base.Base):
    __tablename__ = "refund_lines"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    quantity: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    subtotal: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    order_line_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("order_lines.id", ondelete="RESTRICT"), nullable=False, index=True)
    refund_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("refunds.id", ondelete="CASCADE"), nullable=False, index=True)
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

    order_line: _orm.Mapped["OrderLine"] = _orm.relationship('OrderLine', back_populates='refund_lines', foreign_keys="[RefundLine.order_line_id]")
    refund: _orm.Mapped["Refund"] = _orm.relationship('Refund', back_populates='lines', foreign_keys="[RefundLine.refund_id]")
