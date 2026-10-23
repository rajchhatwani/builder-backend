"""SQLAlchemy model for CustomerAddress (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.customers import Customer


class CustomerAddress(_models_base.Base):
    __tablename__ = "customer_addresses"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    company: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    address1: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    address2: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    city: _orm.Mapped[str] = _orm.mapped_column(_sa.String(100), nullable=False)
    province: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(100), nullable=True)
    province_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(10), nullable=True)
    country: _orm.Mapped[str] = _orm.mapped_column(_sa.String(100), nullable=False)
    country_code: _orm.Mapped[str] = _orm.mapped_column(_sa.String(2), nullable=False)
    postal_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(20), nullable=True)
    phone: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(30), nullable=True)
    is_default: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    customer_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
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

    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='addresses', foreign_keys="[CustomerAddress.customer_id]")
