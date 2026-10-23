"""SQLAlchemy model for CartLine (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.carts import Cart
    from app.models.variants import Variant


class CartLine(_models_base.Base):
    __tablename__ = "cart_lines"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    quantity: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=1)
    properties: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    cart_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("variants.id", ondelete="RESTRICT"), nullable=False, index=True)
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

    cart: _orm.Mapped["Cart"] = _orm.relationship('Cart', back_populates='lines', foreign_keys="[CartLine.cart_id]")
    variant: _orm.Mapped["Variant"] = _orm.relationship('Variant', back_populates='cart_lines', foreign_keys="[CartLine.variant_id]")
