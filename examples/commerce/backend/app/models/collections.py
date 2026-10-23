"""SQLAlchemy model for Collection (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.products import Product


class Collection(_models_base.Base):
    __tablename__ = "collections"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    handle: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False, index=True)
    description_html: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    kind: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='manual')
    rules: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    sort_order: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='manual')
    published: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    published_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    seo_title: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(70), nullable=True)
    seo_description: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(320), nullable=True)
    parent_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
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

    parent: _orm.Mapped["Collection"] = _orm.relationship('Collection', back_populates='children', foreign_keys="[Collection.parent_id]", remote_side="[Collection.id]")
    children: _orm.Mapped[list["Collection"]] = _orm.relationship('Collection', back_populates='parent', foreign_keys="[Collection.parent_id]", passive_deletes=True)
    products: _orm.Mapped[list["Product"]] = _orm.relationship('Product', secondary='collections_products', primaryjoin="Collection.id == collections_products.c.left_id", secondaryjoin="Product.id == collections_products.c.right_id", back_populates='collections', passive_deletes=True)
