"""SQLAlchemy model for Shelf (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.books import Book


class Shelf(_models_base.Base):
    __tablename__ = "shelves"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    label: _orm.Mapped[str] = _orm.mapped_column(_sa.String(30), nullable=False, unique=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    books_on_shelf: _orm.Mapped[list["Book"]] = _orm.relationship('Book', back_populates='shelf', foreign_keys="[Book.shelf_id]", passive_deletes=True)
