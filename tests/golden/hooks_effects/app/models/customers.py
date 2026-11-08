"""SQLAlchemy model for Customer (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.orders import Order


class Customer(_models_base.Base):
    __tablename__ = "customers"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    email: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    api_token: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(100), nullable=True)
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

    orders: _orm.Mapped[list["Order"]] = _orm.relationship('Order', back_populates='customer', foreign_keys="[Order.customer_id]", passive_deletes=True)
