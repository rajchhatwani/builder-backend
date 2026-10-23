"""SQLAlchemy model for Store (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class Store(_models_base.Base):
    __tablename__ = "stores"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    legal_name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(254), nullable=False)
    domain: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(253), nullable=True, index=True)
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False, default='USD')
    timezone: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='UTC')
    weight_unit: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='kg')
    plan: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='trial')
    password_protected: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
    settings: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
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
