"""SQLAlchemy model for OrderEvent (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.orders import Order


class OrderEvent(_models_base.Base):
    __tablename__ = "order_events"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    verb: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    message: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    actor: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(254), nullable=True)
    data: _orm.Mapped[_t.Any] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    order_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
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

    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='events', foreign_keys="[OrderEvent.order_id]")
