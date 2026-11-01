"""SQLAlchemy model for Supplier (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

if _t.TYPE_CHECKING:
    from app.models.invoices import Invoice


class Supplier(_models_base.Base):
    __tablename__ = "suppliers"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    email: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False, unique=True)
    payment_terms: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(40), nullable=True)
    active: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    invoices: _orm.Mapped[list["Invoice"]] = _orm.relationship('Invoice', back_populates='supplier', foreign_keys="[Invoice.supplier_id]", passive_deletes=True)
