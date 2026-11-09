"""SQLAlchemy model for Contact (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class Contact(_models_base.Base):
    __tablename__ = "contacts"
    __table_args__ = (_sa.Index("ix_contacts_custom_fields", "custom_fields", postgresql_using="gin"),)

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    full_name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    custom_fields: _orm.Mapped[dict[str, _t.Any]] = _orm.mapped_column(
        _pg.JSONB(), nullable=False, default=dict, server_default=_sa.text("'{}'::jsonb")
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
