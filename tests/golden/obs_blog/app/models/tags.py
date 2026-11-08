"""SQLAlchemy model for Tag (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.posts import Post


class Tag(_models_base.Base):
    __tablename__ = "tags"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(50), nullable=False, unique=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    posts: _orm.Mapped[list["Post"]] = _orm.relationship('Post', secondary='posts_tags', primaryjoin="Tag.id == posts_tags.c.right_id", secondaryjoin="Post.id == posts_tags.c.left_id", back_populates='tags', passive_deletes=True)
