"""API platform tables (generated). A key is stored as its sha256 hash and an 8 character prefix, never in clear;
`platform_audit.detail` holds ids and slugs, never a key or a field value."""

import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


def _now() -> _dt.datetime:
    return _models_base.utcnow()


class ApiKey(_models_base.Base):
    """kind 'key' is a key an administrator issued; kind 'app' is the token of an app installation."""

    __tablename__ = "api_keys"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    kind: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    prefix: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False)
    key_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    environment: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False)
    scopes: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.ARRAY(_sa.Text()), nullable=False)
    app: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(40), nullable=True)
    event_types: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.ARRAY(_sa.Text()), nullable=False)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_by: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    expires_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    revoked_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    revoked_by: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    last_used_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _sa.UniqueConstraint("prefix", name="uq_api_keys_prefix"),
        _sa.Index("ix_api_keys_tenant", "tenant_id"),
    )


class ApiKeyUsage(_models_base.Base):
    """One fixed rate-limit window of one key (shared by every worker through the database)."""

    __tablename__ = "api_key_usage"

    key_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True)
    window_start: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), primary_key=True)
    count: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)


class PlatformAudit(_models_base.Base):
    __tablename__ = "platform_audit"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    actor: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    action: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), nullable=False)
    target: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(80), nullable=True)
    detail: _orm.Mapped[dict[str, _t.Any]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)

    __table_args__ = (_sa.Index("ix_platform_audit_at", "at"),)
