"""SQLAlchemy model for Profile (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.members import Member


class Profile(_models_base.Base):
    __tablename__ = "profiles"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    bio: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    member_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    member: _orm.Mapped["Member"] = _orm.relationship('Member', back_populates='profile', foreign_keys="[Profile.member_id]")
