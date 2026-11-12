"""Ledger tables (generated). Append-only: the database refuses UPDATE and DELETE on transactions and entries
(see alembic/versions/0030_money_ledger.py). Balances are never stored: they are SUM(entries.amount)."""

import datetime as _dt
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base

ACCOUNT_KINDS = ("asset", "liability", "equity", "income", "expense")


class LedgerAccount(_models_base.Base):
    __tablename__ = "ledger_accounts"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), primary_key=True, default=_uuid.uuid4, server_default=_sa.text("gen_random_uuid()")
    )
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_ledger_accounts_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    name: _orm.Mapped[str] = _orm.mapped_column(_sa.String(200), nullable=False)
    kind: _orm.Mapped[str] = _orm.mapped_column(_sa.String(16), nullable=False)
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow, server_default=_sa.text("now()")
    )

    __table_args__ = (
        _sa.UniqueConstraint("tenant_id", "code", name="uq_ledger_accounts_code"),
        _sa.UniqueConstraint("id", "currency", name="uq_ledger_accounts_id_currency"),
        _sa.CheckConstraint(
            "kind IN ('asset', 'liability', 'equity', 'income', 'expense')", name="ck_ledger_accounts_kind"
        ),
    )


class LedgerTransaction(_models_base.Base):
    __tablename__ = "ledger_transactions"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), primary_key=True, default=_uuid.uuid4, server_default=_sa.text("gen_random_uuid()")
    )
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey(
            "auth_tenants.id", name="fk_ledger_transactions_tenant_id_auth_tenants", ondelete="RESTRICT"
        ),
        nullable=False,
        index=True,
    )
    idempotency_key: _orm.Mapped[str] = _orm.mapped_column(_sa.String(128), nullable=False)
    # sha256 of the request: the same key with another body is a conflict, not a replay
    request_hash: _orm.Mapped[str] = _orm.mapped_column(_sa.String(64), nullable=False)
    description: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(500), nullable=True)
    reference: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(128), nullable=True)
    # set on a reversal: the transaction it cancels. Unique: a transaction is reversed at most once.
    reverses_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey(
            "ledger_transactions.id", name="fk_ledger_transactions_reverses_id_ledger_transactions"
        ),
        nullable=True,
    )
    posted_by: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(_sa.Uuid(), nullable=True)
    posted_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow, server_default=_sa.text("now()")
    )

    __table_args__ = (
        _sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ledger_transactions_idempotency_key"),
        _sa.UniqueConstraint("reverses_id", name="uq_ledger_transactions_reverses_id"),
    )


class LedgerEntry(_models_base.Base):
    __tablename__ = "ledger_entries"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.Uuid(), primary_key=True, default=_uuid.uuid4, server_default=_sa.text("gen_random_uuid()")
    )
    tenant_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", name="fk_ledger_entries_tenant_id_auth_tenants", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(
        _sa.ForeignKey("ledger_transactions.id", name="fk_ledger_entries_transaction_id_ledger_transactions"),
        nullable=False,
        index=True,
    )
    account_id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), nullable=False, index=True)
    # the account's currency, copied here so the foreign key below can pin it: an entry cannot name a currency
    # other than its account's
    currency: _orm.Mapped[str] = _orm.mapped_column(_sa.String(3), nullable=False)
    # signed integer minor units: positive = debit, negative = credit; never zero
    amount: _orm.Mapped[int] = _orm.mapped_column(_sa.BigInteger(), nullable=False)
    line_no: _orm.Mapped[int] = _orm.mapped_column(_sa.Integer(), nullable=False)
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow, server_default=_sa.text("now()")
    )

    __table_args__ = (
        _sa.ForeignKeyConstraint(
            ["account_id", "currency"],
            ["ledger_accounts.id", "ledger_accounts.currency"],
            name="fk_ledger_entries_account_id_ledger_accounts",
        ),
        _sa.UniqueConstraint("transaction_id", "line_no", name="uq_ledger_entries_transaction_id"),
        _sa.CheckConstraint("amount <> 0", name="ck_ledger_entries_amount_nonzero"),
    )
