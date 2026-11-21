"""The credential vault table (generated)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base


class ProviderCredential(_models_base.Base):
    """One encrypted secret of one tenant for one provider. `ciphertext` is the only place a secret lives."""

    __tablename__ = "provider_credentials"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    provider: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    key_name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    ciphertext: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    key_version: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    # a keyed hash tag of the value, to tell two secrets apart in a listing; it cannot be reversed
    fingerprint: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    rotated_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    created_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)

    __table_args__ = (
        _sa.UniqueConstraint("tenant_id", "provider", "key_name", name="uq_provider_credentials_key"),
        _sa.Index("ix_provider_credentials_tenant", "tenant_id", "provider"),
    )
