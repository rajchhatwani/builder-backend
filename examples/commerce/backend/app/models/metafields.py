"""SQLAlchemy model for Metafield (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class Metafield(_models_base.Base):
    __tablename__ = "metafields"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    owner_type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False, index=True)
    owner_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False, index=True)
    namespace: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), nullable=False)
    key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), nullable=False)
    value_type: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    value: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=False)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", ondelete="RESTRICT"), nullable=True, index=True
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
