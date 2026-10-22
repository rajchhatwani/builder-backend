"""SQLAlchemy model for Author (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.books import Book


class Author(_models_base.Base):
    __tablename__ = "authors"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False, unique=True)
    bio: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    born_on: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True)
    rating: _orm.Mapped[float | None] = _orm.mapped_column(_sa.Float(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    books: _orm.Mapped[list["Book"]] = _orm.relationship('Book', back_populates='author', foreign_keys="[Book.author_id]", passive_deletes=True)
