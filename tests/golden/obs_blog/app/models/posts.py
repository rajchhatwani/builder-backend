"""SQLAlchemy model for Post (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.comments import Comment
    from app.models.tags import Tag
    from app.models.users import User


class Post(_models_base.Base):
    __tablename__ = "posts"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    body: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    published: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=False)
    views: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    author_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    author: _orm.Mapped["User"] = _orm.relationship('User', back_populates='posts', foreign_keys="[Post.author_id]")
    comments: _orm.Mapped[list["Comment"]] = _orm.relationship('Comment', back_populates='post', foreign_keys="[Comment.post_id]", passive_deletes=True)
    tags: _orm.Mapped[list["Tag"]] = _orm.relationship('Tag', secondary='posts_tags', primaryjoin="Post.id == posts_tags.c.left_id", secondaryjoin="Tag.id == posts_tags.c.right_id", back_populates='posts', passive_deletes=True)
