"""SQLAlchemy model for Fulfillment (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.fulfillment_lines import FulfillmentLine
    from app.models.locations import Location
    from app.models.orders import Order


class Fulfillment(_models_base.Base):
    __tablename__ = "fulfillments"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False, default='pending')
    tracking_company: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True)
    tracking_number: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(120), nullable=True, index=True)
    tracking_url: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(2000), nullable=True)
    notify_customer: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    shipped_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    location_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True)
    order_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
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

    location: _orm.Mapped["Location"] = _orm.relationship('Location', back_populates='fulfillments', foreign_keys="[Fulfillment.location_id]")
    order: _orm.Mapped["Order"] = _orm.relationship('Order', back_populates='fulfillments', foreign_keys="[Fulfillment.order_id]")
    lines: _orm.Mapped[list["FulfillmentLine"]] = _orm.relationship('FulfillmentLine', back_populates='fulfillment', foreign_keys="[FulfillmentLine.fulfillment_id]", passive_deletes=True)
