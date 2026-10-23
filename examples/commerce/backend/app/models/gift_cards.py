"""SQLAlchemy model for GiftCard (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.customers import Customer


class GiftCard(_models_base.Base):
    __tablename__ = "gift_cards"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    code: _orm.Mapped[str] = _orm.mapped_column(_sa.String(32), nullable=False, unique=True)
    initial_value: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    balance: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False, default=_decimal.Decimal('0'))
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False)
    expires_on: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True)
    disabled: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    note: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
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

    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='gift_cards', foreign_keys="[GiftCard.customer_id]")
