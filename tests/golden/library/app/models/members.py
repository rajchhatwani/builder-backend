"""SQLAlchemy model for Member (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.books import Book
    from app.models.profiles import Profile


class Member(_models_base.Base):
    __tablename__ = "members"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False, unique=True)
    joined_on: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True, default=_dt.date.fromisoformat('2026-01-01'))
    sponsor_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("members.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    sponsor: _orm.Mapped["Member"] = _orm.relationship('Member', back_populates='sponsored', foreign_keys="[Member.sponsor_id]", remote_side="[Member.id]")
    borrowed_books: _orm.Mapped[list["Book"]] = _orm.relationship('Book', secondary='books_borrowers', primaryjoin="Member.id == books_borrowers.c.right_id", secondaryjoin="Book.id == books_borrowers.c.left_id", back_populates='borrowers', passive_deletes=True)
    profile: _orm.Mapped["Profile"] = _orm.relationship('Profile', back_populates='member', foreign_keys="[Profile.member_id]", passive_deletes=True, uselist=False)
    sponsored: _orm.Mapped[list["Member"]] = _orm.relationship('Member', back_populates='sponsor', foreign_keys="[Member.sponsor_id]", passive_deletes=True)
