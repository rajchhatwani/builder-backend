"""SQLAlchemy model for Article (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.blogs import Blog


class Article(_models_base.Base):
    __tablename__ = "articles"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False)
    handle: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False, index=True)
    author: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    body_html: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    summary_html: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    published: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    published_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    tags_cache: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    blog_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
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

    blog: _orm.Mapped["Blog"] = _orm.relationship('Blog', back_populates='articles', foreign_keys="[Article.blog_id]")
