"""SQLAlchemy model for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class Order(_models_base.Base):
    __tablename__ = "orders"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    customer: _orm.Mapped[str] = _orm.mapped_column(_sa.String(120), nullable=False)
    total: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    stage: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    invoice_no: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False, unique=True)
    order_no: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False, unique=True)
    ticket_no: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False, unique=True)
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
