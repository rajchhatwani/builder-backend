"""SQLAlchemy model for Product (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.collections import Collection
    from app.models.product_images import ProductImage
    from app.models.reviews import Review
    from app.models.tags import Tag
    from app.models.variants import Variant


class Product(_models_base.Base):
    __tablename__ = "products"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    handle: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False, index=True)
    description_html: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    vendor: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True, index=True)
    product_type: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True, index=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default='draft')
    tags_cache: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    options: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    published_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    seo_title: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(70), nullable=True)
    seo_description: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(320), nullable=True)
    requires_shipping: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    taxable: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
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
    deleted_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=True
    )

    collections: _orm.Mapped[list["Collection"]] = _orm.relationship('Collection', secondary='collections_products', primaryjoin="Product.id == collections_products.c.right_id", secondaryjoin="Collection.id == collections_products.c.left_id", back_populates='products', passive_deletes=True)
    images: _orm.Mapped[list["ProductImage"]] = _orm.relationship('ProductImage', back_populates='product', foreign_keys="[ProductImage.product_id]", passive_deletes=True)
    reviews: _orm.Mapped[list["Review"]] = _orm.relationship('Review', back_populates='product', foreign_keys="[Review.product_id]", passive_deletes=True)
    tags: _orm.Mapped[list["Tag"]] = _orm.relationship('Tag', secondary='products_tags', primaryjoin="Product.id == products_tags.c.left_id", secondaryjoin="Tag.id == products_tags.c.right_id", back_populates='products', passive_deletes=True)
    variants: _orm.Mapped[list["Variant"]] = _orm.relationship('Variant', back_populates='product', foreign_keys="[Variant.product_id]", passive_deletes=True)
