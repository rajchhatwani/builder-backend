"""Reconciliation tables (generated). A match is a row with UNIQUE(line) and UNIQUE(entry): the database refuses
to pair a ledger entry twice. Un-matching deletes the match row; every action is kept in the append-only
reconciliation_events log."""

import datetime as _dt
import uuid as _uuid
from typing import Any

import sqlalchemy as _sa
from sqlalchemy import orm as _orm
from sqlalchemy.dialects import postgresql as _pg

from app.models import _base as _models_base


def _id() -> _orm.Mapped[_uuid.UUID]:
    return _orm.mapped_column(
        _sa.Uuid(), primary_key=True, default=_uuid.uuid4, server_default=_sa.text("gen_random_uuid()")
    )


def _created() -> _orm.Mapped[_dt.datetime]:
    return _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow, server_default=_sa.text("now()")
    )


class ReconciliationRun(_models_base.Base):
    __tablename__ = "reconciliation_runs"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_reconciliation_runs_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    request_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    account_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("ledger_accounts.id", name="fk_reconciliation_runs_account_id_ledger_accounts"),
        nullable=False,
        index=True,
    )
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False)
    name: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(200), nullable=True)
    period_start: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True)
    period_end: _orm.Mapped[_dt.date | None] = _orm.mapped_column(_sa.Date(), nullable=True)
    status: _orm.Mapped[str] = _orm.mapped_column(_sa.String(8), nullable=False, default="open", server_default="open")
    summary: _orm.Mapped[dict[str, Any] | None] = _orm.mapped_column(_pg.JSONB(), nullable=True)
    created_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _created()
    closed_at: _orm.Mapped[_dt.datetime | None] = _orm.mapped_column(_sa.DateTime(timezone=True), nullable=True)
    closed_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)

    __table_args__ = (
        _sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_reconciliation_runs_idempotency_key"),
        _sa.CheckConstraint("status IN ('open', 'closed')", name="ck_reconciliation_runs_status"),
    )


class ReconciliationLine(_models_base.Base):
    __tablename__ = "reconciliation_lines"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_reconciliation_lines_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    run_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("reconciliation_runs.id", name="fk_reconciliation_lines_run_id_reconciliation_runs"),
        nullable=False,
        index=True,
    )
    line_no: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    external_id: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    line_date: _orm.Mapped[_dt.date] = _orm.mapped_column(_sa.Date(), nullable=False)
    amount: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False)
    reference: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(128), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (
        _sa.UniqueConstraint("run_id", "external_id", name="uq_reconciliation_lines_run_id_external_id"),
        _sa.UniqueConstraint("run_id", "line_no", name="uq_reconciliation_lines_run_id_line_no"),
        _sa.CheckConstraint("amount <> 0", name="ck_reconciliation_lines_amount_nonzero"),
    )


class ReconciliationMatch(_models_base.Base):
    __tablename__ = "reconciliation_matches"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_reconciliation_matches_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    run_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("reconciliation_runs.id", name="fk_reconciliation_matches_run_id_reconciliation_runs"),
        nullable=False,
        index=True,
    )
    line_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("reconciliation_lines.id", name="fk_reconciliation_matches_line_id_reconciliation_lines"),
        nullable=False,
    )
    entry_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("ledger_entries.id", name="fk_reconciliation_matches_entry_id_ledger_entries"),
        nullable=False,
    )
    method: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)
    diff_minor: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    matched_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    matched_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (
        # the database, not the code, guarantees one-to-one: an entry (and a line) is matched at most once
        _sa.UniqueConstraint("entry_id", name="uq_reconciliation_matches_entry_id"),
        _sa.UniqueConstraint("line_id", name="uq_reconciliation_matches_line_id"),
        _sa.CheckConstraint(
            "method IN ('exact_reference', 'exact', 'tolerance', 'manual')", name="ck_reconciliation_matches_method"
        ),
    )


class ReconciliationEvent(_models_base.Base):
    __tablename__ = "reconciliation_events"

    id: _orm.Mapped[_uuid.UUID] = _id()
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_reconciliation_events_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    run_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("reconciliation_runs.id", name="fk_reconciliation_events_run_id_reconciliation_runs"),
        nullable=False,
        index=True,
    )
    action: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)
    line_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    entry_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    method: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(16), nullable=True)
    actor: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    created_at: _orm.Mapped[_dt.datetime] = _created()

    __table_args__ = (
        _sa.CheckConstraint(
            "action IN ('import', 'match', 'unmatch', 'close')", name="ck_reconciliation_events_action"
        ),
    )
