"""SQLAlchemy model for TaxRate (generated)."""
import datetime as _dt
import decimal as _decimal
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class TaxRate(_models_base.Base):
    __tablename__ = "tax_rates"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    country_code: _orm.Mapped[str] = _orm.mapped_column(_sa.String(2), nullable=False, index=True)
    province_code: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(10), nullable=True)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(100), nullable=False)
    rate: _orm.Mapped[_decimal.Decimal] = _orm.mapped_column(_sa.Numeric(18, 6), nullable=False)
    includes_shipping: _orm.Mapped[bool | None] = _orm.mapped_column(_sa.Boolean(), nullable=True, default=False)
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
