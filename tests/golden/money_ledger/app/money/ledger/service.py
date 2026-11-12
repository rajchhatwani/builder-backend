"""Ledger service (generated). The rules, in one place.

* Amounts are integer minor units; positive = debit, negative = credit. Floats never get here (the request
  models are strict) and nothing below converts to float.
* A transaction posts atomically: one header row, its entries, one COMMIT. The database refuses the commit when
  the entries do not sum to zero per currency (deferred constraint trigger); the checks here only give a
  precise error before that.
* `idempotency_key` makes a post safe to repeat: the same key with the same request returns the first result;
  the same key with a different request is a 409. Parallel posts of one key create exactly one transaction.
* Nothing is updated or deleted. A correction is a REVERSAL transaction: the same entries with the signs
  flipped, linked through `reverses_id` (unique: a transaction is reversed once).
* Balances are SUM(entries): no stored counters, so there are no row locks and no lock order to get wrong.
"""

import hashlib
import json
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy.dialects import postgresql as _pg
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.money import currency as _money
from app.money import settings as _settings
from app.money.ledger import config as _config
from app.money.ledger import schemas as _s
from app.money.ledger.models import LedgerAccount, LedgerEntry, LedgerTransaction

Tenant = _uuid.UUID | None
# ledger transactions posted by the invoicing block (keys invoice:/payment:/payout:) are corrected through it
MANAGED_KEY_PREFIXES = ("invoice:", "payment:", "payout:")


def tenant_of(user: _t.Any) -> Tenant:
    """The caller's tenant (multi-tenant projects only); every query below is confined to it."""
    if not _config.MULTI_TENANT:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise AppError("forbidden", "this ledger needs a caller that belongs to a tenant", 403)
    return _t.cast(_uuid.UUID, tenant)


def _scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


def direction(amount: int) -> str:
    return "debit" if amount > 0 else "credit"


def account_out(row: LedgerAccount) -> _s.AccountOut:
    return _s.AccountOut(
        id=row.id,
        code=row.code,
        name=row.name,
        kind=_t.cast(_s.AccountKind, row.kind),
        currency=row.currency,
        exponent=_money.exponent(row.currency),
        created_at=row.created_at,
    )


def _entry_out(row: LedgerEntry) -> _s.EntryOut:
    return _s.EntryOut(
        id=row.id,
        line_no=row.line_no,
        account_id=row.account_id,
        currency=row.currency,
        amount_minor=row.amount,
        direction=_t.cast(_t.Literal["debit", "credit"], direction(row.amount)),
    )


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


async def _transaction_outs(
    session: AsyncSession, rows: _t.Sequence[LedgerTransaction]
) -> list[_s.TransactionOut]:
    ids = [r.id for r in rows]
    entries: dict[_uuid.UUID, list[_s.EntryOut]] = {i: [] for i in ids}
    reversed_by: dict[_uuid.UUID, _uuid.UUID] = {}
    if ids:
        found = await session.execute(
            _sa.select(LedgerEntry)
            .where(LedgerEntry.transaction_id.in_(ids))
            .order_by(LedgerEntry.transaction_id, LedgerEntry.line_no)
        )
        for entry in found.scalars():
            entries[entry.transaction_id].append(_entry_out(entry))
        reversals = await session.execute(
            _sa.select(LedgerTransaction.reverses_id, LedgerTransaction.id).where(
                LedgerTransaction.reverses_id.in_(ids)
            )
        )
        reversed_by = {original: reversal for original, reversal in reversals.all()}
    return [
        _s.TransactionOut(
            id=r.id,
            idempotency_key=r.idempotency_key,
            description=r.description,
            reference=r.reference,
            reverses_id=r.reverses_id,
            reversed_by_id=reversed_by.get(r.id),
            posted_at=r.posted_at,
            posted_by=r.posted_by,
            entries=entries[r.id],
        )
        for r in rows
    ]


# --- accounts ----------------------------------------------------------------------------------


async def create_account(session: AsyncSession, user: _t.Any, body: _s.AccountCreate) -> _s.AccountOut:
    tenant = tenant_of(user)
    if body.currency not in _settings.CURRENCIES:
        raise AppError(
            "unsupported_currency",
            f"currency must be one of {', '.join(_settings.CURRENCIES)}",
            422,
        )
    values: dict[str, _t.Any] = {
        "code": body.code,
        "name": body.name,
        "kind": body.kind,
        "currency": body.currency,
    }
    if tenant is not None:
        values["tenant_id"] = tenant
    row = LedgerAccount(**values)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_ledger_accounts_code" in str(exc.orig):
            raise AppError("duplicate_account", f"an account with code {body.code!r} exists", 409) from exc
        raise
    return account_out(row)


async def list_accounts(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, currency: str | None
) -> tuple[list[_s.AccountOut], int]:
    tenant = tenant_of(user)
    base = _scoped(_sa.select(LedgerAccount), LedgerAccount, tenant)
    if currency is not None:
        base = base.where(LedgerAccount.currency == currency)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(base.order_by(LedgerAccount.code).limit(limit).offset(offset))
    return [account_out(r) for r in rows.scalars()], int(total)


async def account_entries(
    session: AsyncSession, user: _t.Any, account_id: _uuid.UUID, limit: int, offset: int
) -> tuple[list[_s.AccountEntryOut], int]:
    tenant = tenant_of(user)
    found = await session.execute(
        _scoped(_sa.select(LedgerAccount.id).where(LedgerAccount.id == account_id), LedgerAccount, tenant)
    )
    if found.scalar_one_or_none() is None:
        raise AppError("not_found", "account not found", 404)
    where = _scoped(
        _sa.select(LedgerEntry.id).where(LedgerEntry.account_id == account_id), LedgerEntry, tenant
    )
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(where.subquery()))).scalar_one()
    rows = await session.execute(
        _scoped(
            _sa.select(LedgerEntry, LedgerTransaction)
            .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
            .where(LedgerEntry.account_id == account_id),
            LedgerEntry,
            tenant,
        )
        .order_by(LedgerTransaction.posted_at.desc(), LedgerEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        _s.AccountEntryOut(
            id=e.id,
            transaction_id=e.transaction_id,
            line_no=e.line_no,
            currency=e.currency,
            amount_minor=e.amount,
            direction=_t.cast(_t.Literal["debit", "credit"], direction(e.amount)),
            posted_at=t.posted_at,
            description=t.description,
            reverses_id=t.reverses_id,
        )
        for e, t in rows.all()
    ]
    return items, int(total)


# --- transactions ------------------------------------------------------------------------------


async def _existing_by_key(session: AsyncSession, tenant: Tenant, key: str) -> LedgerTransaction | None:
    stmt = _scoped(
        _sa.select(LedgerTransaction).where(LedgerTransaction.idempotency_key == key), LedgerTransaction, tenant
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _replay_or_conflict(
    session: AsyncSession, tenant: Tenant, key: str, fingerprint: str
) -> _s.TransactionOut | None:
    existing = await _existing_by_key(session, tenant, key)
    if existing is None:
        return None
    if existing.request_hash != fingerprint:
        raise AppError(
            "idempotency_conflict", "this idempotency_key was already used for a different request", 409
        )
    return (await _transaction_outs(session, [existing]))[0]


async def _write(
    session: AsyncSession,
    user: _t.Any,
    tenant: Tenant,
    *,
    key: str,
    fingerprint: str,
    description: str | None,
    reference: str | None,
    reverses_id: _uuid.UUID | None,
    lines: list[tuple[_uuid.UUID, str, int]],
) -> tuple[_s.TransactionOut, bool]:
    """Insert header + entries and commit. Returns (transaction, replayed)."""
    tx_id = _uuid.uuid4()
    header: dict[str, _t.Any] = {
        "id": tx_id,
        "idempotency_key": key,
        "request_hash": fingerprint,
        "description": description,
        "reference": reference,
        "reverses_id": reverses_id,
        "posted_by": getattr(user, "id", None),
    }
    index = ["idempotency_key"]
    if tenant is not None:
        header["tenant_id"] = tenant
        index = ["tenant_id", "idempotency_key"]
    try:
        # ON CONFLICT waits for a parallel post of the same key to finish, then does nothing: the loser reads
        # the winner's row below (replay), it never creates a second transaction.
        inserted = await session.execute(
            _pg.insert(LedgerTransaction)
            .values(**header)
            .on_conflict_do_nothing(index_elements=index)
            .returning(LedgerTransaction.id)
        )
        if inserted.scalar_one_or_none() is None:
            await session.rollback()
            replay = await _replay_or_conflict(session, tenant, key, fingerprint)
            if replay is None:  # the winner vanished (cannot happen: rows are never deleted)
                raise AppError("conflict", "could not post, retry", 409)
            return replay, True
        rows = []
        for number, (account_id, code, amount) in enumerate(lines, start=1):
            row: dict[str, _t.Any] = {
                "id": _uuid.uuid4(),
                "transaction_id": tx_id,
                "account_id": account_id,
                "currency": code,
                "amount": amount,
                "line_no": number,
            }
            if tenant is not None:
                row["tenant_id"] = tenant
            rows.append(row)
        await session.execute(_sa.insert(LedgerEntry), rows)
        await session.commit()  # the deferred constraint trigger runs here
    except IntegrityError as exc:
        await session.rollback()
        text = str(exc.orig)
        if "uq_ledger_transactions_reverses_id" in text:
            replay = await _replay_or_conflict(session, tenant, key, fingerprint)
            if replay is not None:
                return replay, True
            raise AppError("already_reversed", "this transaction has already been reversed", 409) from exc
        if "does not sum to zero" in text or "at least two entries" in text or "mixes tenants" in text:
            raise AppError("unbalanced", "the entries do not balance", 422) from exc
        if "only be added in the transaction that created" in text:
            raise AppError(
                "ledger_transaction_scope",
                "ledger entries must be posted in the same database transaction as their header (no savepoint around the header)",
                409,
            ) from exc
        raise
    stored = (await session.execute(_sa.select(LedgerTransaction).where(LedgerTransaction.id == tx_id))).scalar_one()
    return (await _transaction_outs(session, [stored]))[0], False


def _unbalanced(sums: dict[str, int]) -> AppError:
    return AppError(
        "unbalanced",
        "the entries of a transaction must sum to zero in every currency",
        422,
        [{"currency": c, "sum_minor": s} for c, s in sorted(sums.items()) if s != 0],
    )


async def post_transaction(
    session: AsyncSession, user: _t.Any, body: _s.TransactionIn
) -> tuple[_s.TransactionOut, bool]:
    tenant = tenant_of(user)
    if any(e.amount_minor == 0 for e in body.entries):
        raise AppError("invalid_entries", "an entry amount cannot be zero", 422)
    fingerprint = _fingerprint(
        "post", body.description, body.reference, [[str(e.account_id), e.amount_minor] for e in body.entries]
    )
    replay = await _replay_or_conflict(session, tenant, body.idempotency_key, fingerprint)
    if replay is not None:
        return replay, True
    ids = sorted({e.account_id for e in body.entries}, key=str)
    found = await session.execute(
        _scoped(_sa.select(LedgerAccount).where(LedgerAccount.id.in_(ids)), LedgerAccount, tenant)
    )
    accounts = {a.id: a for a in found.scalars()}
    missing = [str(i) for i in ids if i not in accounts]
    if missing:
        raise AppError("unknown_account", "an entry names an account that does not exist", 422, [{"account_id": m} for m in missing])
    sums: dict[str, int] = {}
    lines: list[tuple[_uuid.UUID, str, int]] = []
    for e in body.entries:
        code = accounts[e.account_id].currency
        sums[code] = sums.get(code, 0) + e.amount_minor
        lines.append((e.account_id, code, e.amount_minor))
    if any(total != 0 for total in sums.values()):
        raise _unbalanced(sums)
    return await _write(
        session,
        user,
        tenant,
        key=body.idempotency_key,
        fingerprint=fingerprint,
        description=body.description,
        reference=body.reference,
        reverses_id=None,
        lines=lines,
    )


async def reverse_transaction(
    session: AsyncSession, user: _t.Any, transaction_id: _uuid.UUID, body: _s.ReverseIn
) -> tuple[_s.TransactionOut, bool]:
    tenant = tenant_of(user)
    fingerprint = _fingerprint("reverse", str(transaction_id), body.description)
    replay = await _replay_or_conflict(session, tenant, body.idempotency_key, fingerprint)
    if replay is not None:
        return replay, True
    original = (
        await session.execute(
            _scoped(
                _sa.select(LedgerTransaction).where(LedgerTransaction.id == transaction_id),
                LedgerTransaction,
                tenant,
            )
        )
    ).scalar_one_or_none()
    if original is None:
        raise AppError("not_found", "transaction not found", 404)
    if original.idempotency_key.startswith(MANAGED_KEY_PREFIXES):
        raise AppError(
            "managed_transaction",
            "this transaction belongs to an invoice, payment or payout: void or correct it there, not in the ledger",
            409,
        )
    if original.reverses_id is not None:
        raise AppError("cannot_reverse_reversal", "a reversal cannot itself be reversed; post a new transaction", 422)
    already = (
        await session.execute(_sa.select(LedgerTransaction.id).where(LedgerTransaction.reverses_id == original.id))
    ).scalar_one_or_none()
    if already is not None:
        raise AppError("already_reversed", "this transaction has already been reversed", 409)
    entries = (
        await session.execute(
            _sa.select(LedgerEntry).where(LedgerEntry.transaction_id == original.id).order_by(LedgerEntry.line_no)
        )
    ).scalars().all()
    lines = [(e.account_id, e.currency, -e.amount) for e in entries]
    return await _write(
        session,
        user,
        tenant,
        key=body.idempotency_key,
        fingerprint=fingerprint,
        description=body.description or f"Reversal of {original.id}",
        reference=original.reference,
        reverses_id=original.id,
        lines=lines,
    )


async def get_transaction(session: AsyncSession, user: _t.Any, transaction_id: _uuid.UUID) -> _s.TransactionOut:
    tenant = tenant_of(user)
    row = (
        await session.execute(
            _scoped(
                _sa.select(LedgerTransaction).where(LedgerTransaction.id == transaction_id),
                LedgerTransaction,
                tenant,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "transaction not found", 404)
    return (await _transaction_outs(session, [row]))[0]


async def list_transactions(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, account_id: _uuid.UUID | None
) -> tuple[list[_s.TransactionOut], int]:
    tenant = tenant_of(user)
    base = _scoped(_sa.select(LedgerTransaction), LedgerTransaction, tenant)
    if account_id is not None:
        base = base.where(
            _sa.exists().where(
                LedgerEntry.transaction_id == LedgerTransaction.id, LedgerEntry.account_id == account_id
            )
        )
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(
        base.order_by(LedgerTransaction.posted_at.desc(), LedgerTransaction.id.desc()).limit(limit).offset(offset)
    )
    return await _transaction_outs(session, rows.scalars().all()), int(total)


# --- balances ----------------------------------------------------------------------------------


async def balances(session: AsyncSession, user: _t.Any, currency: str | None) -> _s.BalancesOut:
    tenant = tenant_of(user)
    debit = _sa.func.coalesce(_sa.func.sum(_sa.case((LedgerEntry.amount > 0, LedgerEntry.amount), else_=0)), 0)
    credit = _sa.func.coalesce(_sa.func.sum(_sa.case((LedgerEntry.amount < 0, LedgerEntry.amount), else_=0)), 0)
    stmt = (
        _sa.select(LedgerAccount, debit.label("debit"), credit.label("credit"))
        .outerjoin(LedgerEntry, LedgerEntry.account_id == LedgerAccount.id)
        .group_by(LedgerAccount.id)
        .order_by(LedgerAccount.code)
        .limit(_config.BALANCE_ROW_CAP + 1)
    )
    stmt = _scoped(stmt, LedgerAccount, tenant)
    if currency is not None:
        stmt = stmt.where(LedgerAccount.currency == currency)
    items = [
        _s.BalanceOut(
            account_id=a.id,
            code=a.code,
            name=a.name,
            currency=a.currency,
            exponent=_money.exponent(a.currency),
            balance_minor=int(d) + int(c),
            debit_total_minor=int(d),
            credit_total_minor=int(c),
        )
        for a, d, c in (await session.execute(stmt)).all()
    ]
    truncated = len(items) > _config.BALANCE_ROW_CAP
    items = items[: _config.BALANCE_ROW_CAP]
    sums = _scoped(
        _sa.select(LedgerEntry.currency, _sa.func.sum(LedgerEntry.amount)).group_by(LedgerEntry.currency),
        LedgerEntry,
        tenant,
    )
    if currency is not None:
        sums = sums.where(LedgerEntry.currency == currency)
    totals = {code: int(total) for code, total in (await session.execute(sums)).all()}
    for item in items:
        totals.setdefault(item.currency, 0)
    return _s.BalancesOut(
        items=items, truncated=truncated, totals=[_s.CurrencyTotalOut(currency=c, sum_minor=s) for c, s in sorted(totals.items())]
    )
