"""SQLAlchemy model for Comment (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.posts import Post


class Comment(_models_base.Base):
    __tablename__ = "comments"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    body: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    post_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    post: _orm.Mapped["Post"] = _orm.relationship('Post', back_populates='comments', foreign_keys="[Comment.post_id]")
