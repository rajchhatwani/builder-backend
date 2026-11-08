"""SQLAlchemy model for Document (generated)."""
import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Document(_models_base.Base):
    __tablename__ = "documents"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    title: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    pages: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    created_by_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True, index=True
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
