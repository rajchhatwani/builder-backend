"""SQLAlchemy model for Discount (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.discount_usages import DiscountUsage


class Discount(_models_base.Base):
    __tablename__ = "discounts"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    code: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, unique=True)
    title: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    kind: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    value: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    target: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='order')
    minimum_subtotal: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True)
    usage_limit: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    once_per_customer: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    used_count: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    combines_with_other: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    applies_to: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    starts_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    ends_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    active: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
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

    usages: _orm.Mapped[list["DiscountUsage"]] = _orm.relationship('DiscountUsage', back_populates='discount', foreign_keys="[DiscountUsage.discount_id]", passive_deletes=True)
