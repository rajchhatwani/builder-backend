"""Prediction table (generated). Values, interval and actual are integers in the configured unit; the interval always
contains the value (CHECK); an actual can be written once (conditional UPDATE in the service)."""

import datetime as _dt
import uuid as _uuid
from typing import Any

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


class PredictionRecord(_models_base.Base):
    __tablename__ = "prediction_records"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), primary_key=True, default=_uuid.uuid4, server_default=_sa.text("gen_random_uuid()")
    )
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_prediction_records_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: _orm.Mapped[str] = _orm.mapped_column(_sa.String(32), nullable=False)
    subject_ref: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    model_id: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    unit: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)
    value: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    low: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    high: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    features: _orm.Mapped[dict[str, Any]] = _orm.mapped_column(_pg.JSONB(), nullable=False)
    actual: _orm.Mapped[int | None] = _orm.mapped_column(_sa.BigInteger(), nullable=True)
    actual_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    created_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow, server_default=_sa.text("now()")
    )

    __table_args__ = (
        _sa.Index("ix_prediction_records_kind", "tenant_id", "kind", "created_at"),
        _sa.CheckConstraint("low <= value AND value <= high", name="ck_prediction_records_interval"),
    )
