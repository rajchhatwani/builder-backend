"""SQLAlchemy model for Webhook (generated)."""
import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Webhook(_models_base.Base):
    __tablename__ = "webhooks"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    topic: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    url: _orm.Mapped[str] = _orm.mapped_column(_sa.String(2000), nullable=False)
    body_format: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True, default='json')
    secret: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(128), nullable=True)
    active: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
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
