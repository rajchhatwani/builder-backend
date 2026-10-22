"""SQLAlchemy model for Book (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.authors import Author
    from app.models.members import Member
    from app.models.shelves import Shelf


class Book(_models_base.Base):
    __tablename__ = "books"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False, index=True)
    isbn: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(20), nullable=True, unique=True)
    pages: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=100)
    price: _orm.Mapped[_decimal.Decimal | None] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=True, default=_decimal.Decimal('9.99'))
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default='draft')
    published_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    in_stock: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False, default=True)
    extra: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True, default=lambda: {'tags': []})
    catalog_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    author_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("authors.id", ondelete="RESTRICT"), nullable=False, index=True)
    shelf_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("shelves.id", ondelete="SET NULL"), nullable=True, index=True)
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

    author: _orm.Mapped["Author"] = _orm.relationship('Author', back_populates='books', foreign_keys="[Book.author_id]")
    shelf: _orm.Mapped["Shelf"] = _orm.relationship('Shelf', back_populates='books_on_shelf', foreign_keys="[Book.shelf_id]")
    borrowers: _orm.Mapped[list["Member"]] = _orm.relationship('Member', secondary='books_borrowers', primaryjoin="Book.id == books_borrowers.c.left_id", secondaryjoin="Member.id == books_borrowers.c.right_id", back_populates='borrowed_books', passive_deletes=True)
