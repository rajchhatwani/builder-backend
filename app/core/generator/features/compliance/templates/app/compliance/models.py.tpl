"""Compliance tables (generated). `compliance_audit.detail` holds ids and counts, never a field value."""

import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


def _now() -> _dt.datetime:
    return _models_base.utcnow()


class LegalHold(_models_base.Base):
    """While active (released_at is null) the rows it covers are never purged or anonymised. record_id null = the
    whole entity."""

    __tablename__ = "legal_holds"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    entity: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    record_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    reason: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    placed_by: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    placed_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    released_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    released_by: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(64), nullable=True)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)  # null: not tenant scoped

    __table_args__ = (_sa.Index("ix_legal_holds_entity", "entity", "record_id"),)


class Consent(_models_base.Base):
    __tablename__ = "consents"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    subject: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    purpose: _orm.Mapped[str] = _orm.mapped_column(_sa.String(40), nullable=False)
    granted_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    withdrawn_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    recorded_by: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)

    __table_args__ = (_sa.Index("ix_consents_subject", "subject", "purpose"),)


class BreakGlassGrant(_models_base.Base):
    __tablename__ = "break_glass_grants"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    user_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False)
    role: _orm.Mapped[str] = _orm.mapped_column(_sa.String(80), nullable=False)
    reason: _orm.Mapped[str] = _orm.mapped_column(_sa.Text(), nullable=False)
    entity_scope: _orm.Mapped[list[str]] = _orm.mapped_column(_pg.ARRAY(_sa.Text()), nullable=False)
    granted_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    expires_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False)
    revoked_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)

    __table_args__ = (_sa.Index("ix_break_glass_grants_user", "user_id"),)


class ComplianceAudit(_models_base.Base):
    """Append-only by convention. `detail` never contains a protected (or any) field value."""

    __tablename__ = "compliance_audit"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    actor: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    action: _orm.Mapped[str] = _orm.mapped_column(_sa.String(60), nullable=False)
    entity: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(80), nullable=True)
    record_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    detail: _orm.Mapped[dict[str, _t.Any]] = _orm.mapped_column(_sa.JSON(), nullable=False)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)

    __table_args__ = (_sa.Index("ix_compliance_audit_at", "at"),)


class RetentionRun(_models_base.Base):
    __tablename__ = "retention_runs"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=False, default=_now)
    actor: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    dry_run: _orm.Mapped[bool] = _orm.mapped_column(_sa.Boolean(), nullable=False)
    summary: _orm.Mapped[dict[str, _t.Any]] = _orm.mapped_column(_sa.JSON(), nullable=False)
