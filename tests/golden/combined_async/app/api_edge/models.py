"""The API edge tables (generated)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

IN_PROGRESS = "in_progress"
COMPLETED = "completed"


class ApiIdempotency(_models_base.Base):
    """One idempotency key of one caller. The row is claimed in the business transaction and is only
    ever committed together with the write and the response it stands for."""

    __tablename__ = "api_idempotency"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    tenant_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    principal_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    method: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False)
    path: _orm.Mapped[str] = _orm.mapped_column(_sa.String(500), nullable=False)
    request_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False, default=IN_PROGRESS)
    response_status: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    # only content-type and location are kept: never an Authorization or Set-Cookie header
    response_headers: _orm.Mapped[list[list[str]] | None] = _orm.mapped_column(_sa.JSON(), nullable=True)
    response_body: _orm.Mapped[bytes | None] = _orm.mapped_column(_sa.LargeBinary(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    expires_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        _sa.UniqueConstraint("tenant_key", "principal_key", "key", name="uq_api_idempotency_scope_key"),
        _sa.Index("ix_api_idempotency_expires_at", "expires_at"),
    )


class ApiRateBucket(_models_base.Base):
    """A token bucket. Tokens are refilled lazily, in the same UPDATE that takes them."""

    __tablename__ = "api_rate_buckets"

    bucket_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), primary_key=True)
    tokens: _orm.Mapped[float] = _orm.mapped_column(_sa.Double(), nullable=False)
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (_sa.Index("ix_api_rate_buckets_updated_at", "updated_at"),)


class ApiQuotaUsage(_models_base.Base):
    """What a tenant has used of a meter in one period."""

    __tablename__ = "api_quota_usage"

    tenant_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), primary_key=True)
    meter: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), primary_key=True)
    period_start: _orm.Mapped[_dt.date] = _orm.mapped_column(_sa.Date(), primary_key=True)
    used: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
