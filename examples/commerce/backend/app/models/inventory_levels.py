"""SQLAlchemy model for InventoryLevel (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.locations import Location
    from app.models.variants import Variant


class InventoryLevel(_models_base.Base):
    __tablename__ = "inventory_levels"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    available: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False, default=0)
    on_hand: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    committed: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    incoming: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True, default=0)
    location_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    variant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.ForeignKey("variants.id", ondelete="CASCADE"), nullable=False, index=True)
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

    location: _orm.Mapped["Location"] = _orm.relationship('Location', back_populates='inventory_levels', foreign_keys="[InventoryLevel.location_id]")
    variant: _orm.Mapped["Variant"] = _orm.relationship('Variant', back_populates='inventory_levels', foreign_keys="[InventoryLevel.variant_id]")
