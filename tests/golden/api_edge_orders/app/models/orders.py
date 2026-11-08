"""SQLAlchemy model for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.customers import Customer


class Order(_models_base.Base):
    __tablename__ = "orders"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    reference: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), nullable=False)
    total: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    customer_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True)
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

    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='orders', foreign_keys="[Order.customer_id]")
