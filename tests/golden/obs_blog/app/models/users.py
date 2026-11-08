"""SQLAlchemy model for User (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.posts import Post


class User(_models_base.Base):
    __tablename__ = "users"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(255), nullable=False, unique=True)
    display_name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(100), nullable=False)
    role: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='member')
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    posts: _orm.Mapped[list["Post"]] = _orm.relationship('Post', back_populates='author', foreign_keys="[Post.author_id]", passive_deletes=True)
