"""SQLAlchemy model for ProductImage (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.products import Product


class ProductImage(_models_base.Base):
    __tablename__ = "product_images"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    url: _orm.Mapped[str] = _orm.mapped_column(_sa.String(2000), nullable=False)
    alt: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(512), nullable=True)
    position: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=1)
    width: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    height: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
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

    product: _orm.Mapped["Product"] = _orm.relationship('Product', back_populates='images', foreign_keys="[ProductImage.product_id]")
