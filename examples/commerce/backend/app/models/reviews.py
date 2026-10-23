"""SQLAlchemy model for Review (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.customers import Customer
    from app.models.products import Product


class Review(_models_base.Base):
    __tablename__ = "reviews"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    rating: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    title: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    body: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    author_name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    status: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='pending')
    verified_purchase: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    customer_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
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

    customer: _orm.Mapped["Customer"] = _orm.relationship('Customer', back_populates='reviews', foreign_keys="[Review.customer_id]")
    product: _orm.Mapped["Product"] = _orm.relationship('Product', back_populates='reviews', foreign_keys="[Review.product_id]")
