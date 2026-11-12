"""Posting to the ledger from inside another transaction (generated). The ledger's own service commits on every
post; invoices, payments and payouts must change their own rows AND the books in ONE database transaction, so
this module stages a balanced transaction (header + entries) on the caller's session WITHOUT committing. The
database still checks it at COMMIT (deferred trigger: every transaction sums to zero per currency)."""

import hashlib
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.money.ledger.models import LedgerAccount, LedgerEntry, LedgerTransaction

Tenant = _uuid.UUID | None


def tenant_of(user: _t.Any, multi_tenant: bool) -> Tenant:
    if not multi_tenant:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise AppError("forbidden", "this needs a caller that belongs to a tenant", 403)
    return _t.cast(_uuid.UUID, tenant)


def scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


async def resolve_account(session: AsyncSession, tenant: Tenant, code: str, currency: str) -> LedgerAccount:
    """The ledger account for `code` in `currency`: the account named `code` when it is in that currency,
    otherwise the account named `<code>.<CUR>`. 422 `account_missing` when neither exists."""
    wanted = (code, f"{code}.{currency}")
    stmt = scoped(_sa.select(LedgerAccount).where(LedgerAccount.code.in_(wanted)), LedgerAccount, tenant)
    for account in (await session.execute(stmt)).scalars():
        if account.currency == currency:
            return account
    raise AppError(
        "account_missing",
        f"create the ledger account {code!r} (or {code + '.' + currency!r}) in {currency} first",
        422,
        [{"account_code": code, "alternative_code": f"{code}.{currency}", "currency": currency}],
    )


async def stage(
    session: AsyncSession,
    tenant: Tenant,
    user: _t.Any,
    *,
    key: str,
    description: str,
    reference: str | None,
    lines: _t.Sequence[tuple[LedgerAccount, int]],
    reverses_id: _uuid.UUID | None = None,
    tx_id: _uuid.UUID | None = None,
) -> _uuid.UUID:
    """Insert one ledger transaction (zero amounts are skipped) and return its id. No commit, no savepoint."""
    entries = [(account, amount) for account, amount in lines if amount != 0]
    sums: dict[str, int] = {}
    for account, amount in entries:
        sums[account.currency] = sums.get(account.currency, 0) + amount
    if len(entries) < 2 or any(total != 0 for total in sums.values()):
        raise AppError("unbalanced", "the posting does not balance", 500)
    new_id = tx_id or _uuid.uuid4()
    digest = hashlib.sha256(f"{key}|{[(str(a.id), n) for a, n in entries]}".encode()).hexdigest()
    header: dict[str, _t.Any] = {
        "id": new_id,
        "idempotency_key": key,
        "request_hash": digest,
        "description": description[:500],
        "reference": reference,
        "reverses_id": reverses_id,
        "posted_by": getattr(user, "id", None),
    }
    if tenant is not None:
        header["tenant_id"] = tenant
    await session.execute(_sa.insert(LedgerTransaction).values(**header))
    rows = []
    for number, (account, amount) in enumerate(entries, start=1):
        row: dict[str, _t.Any] = {
            "id": _uuid.uuid4(),
            "transaction_id": new_id,
            "account_id": account.id,
            "currency": account.currency,
            "amount": amount,
            "line_no": number,
        }
        if tenant is not None:
            row["tenant_id"] = tenant
        rows.append(row)
    await session.execute(_sa.insert(LedgerEntry), rows)
    return new_id


async def reversal_lines(session: AsyncSession, original: _uuid.UUID) -> list[tuple[LedgerAccount, int]]:
    """The entries of `original` with their signs flipped, as (account, amount)."""
    found = await session.execute(
        _sa.select(LedgerEntry, LedgerAccount)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(LedgerEntry.transaction_id == original)
        .order_by(LedgerEntry.line_no)
    )
    return [(account, -entry.amount) for entry, account in found.all()]
