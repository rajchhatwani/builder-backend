"""Invoicing service (generated). The rules, in one place.

* Invoices are `receivable` (AR: we invoice a customer) or `payable` (AP: a bill from a supplier). Lines carry an
  integer quantity and unit price and an optional named tax rate; the tax of a line is rounded half to even and
  the invoice tax is the sum of its line taxes (app/money/invoicing/totals.py). No float anywhere.
* Status: draft -> issued -> partially_paid -> paid; draft | issued -> void. A draft can be edited; from `issued`
  on the invoice is immutable (service AND database trigger).
* Issuing takes the next number from a counter row (per tenant and kind) in the SAME transaction: the row is
  locked until commit, a rollback gives the number back, so numbers are consecutive and unique.
* Issue, payment and void post to the ledger in the same database transaction as the invoice change (posting.py);
  the ledger's deferred trigger refuses an unbalanced posting at COMMIT.
    AR issue:  debit receivable (total), credit revenue (net), credit tax (tax)    AP issue: the mirror image
    AR payment: debit cash, credit receivable                                       AP payment: debit payable, credit cash
    void: a ledger reversal of the issue transaction (refused once a payment exists)
* Payments are idempotent by `idempotency_key`; the invoice row is locked, so parallel payments never overpay.
"""

import hashlib
import json
import typing as _t
import uuid as _uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as _sa
from sqlalchemy.dialects import postgresql as _pg
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import _base as _models_base
from app.money import currency as _money
from app.money import settings as _settings
from app.money import tax as _tax
from app.money.invoicing import config as _config
from app.money.invoicing import posting as _post
from app.money.invoicing import rules as _rules
from app.money.invoicing import schemas as _s
from app.money.invoicing import totals as _totals
from app.money.invoicing.models import Invoice, InvoiceCounter, InvoiceLine, InvoicePayment

Tenant = _uuid.UUID | None


def tenant_of(user: _t.Any) -> Tenant:
    return _post.tenant_of(user, _config.MULTI_TENANT)


def _scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return _post.scoped(stmt, model, tenant)


def _today() -> date:
    return datetime.now(UTC).date()


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"), sort_keys=True, default=str).encode()).hexdigest()


def _line_values(lines: _t.Sequence[_s.LineIn], currency: str) -> list[tuple[_s.LineIn, _totals.LineTotal]]:
    computed = []
    for line in lines:
        try:
            computed.append((line, _totals.line_total(line.quantity, line.unit_price_minor, currency, line.tax_rate)))
        except _tax.TaxError as exc:
            raise AppError("unknown_tax_rate", str(exc), 422, [{"tax_rate": line.tax_rate}]) from exc
    total = _totals.invoice_total([t for _, t in computed])
    if total.total_minor > _config.MAX_AMOUNT_MINOR:
        raise AppError("amount_too_large", "the invoice total is too large", 422)
    return computed


def _check_currency(code: str) -> None:
    if code not in _settings.CURRENCIES:
        raise AppError("unsupported_currency", f"currency must be one of {', '.join(_settings.CURRENCIES)}", 422)


async def _line_rows(session: AsyncSession, invoice_id: _uuid.UUID) -> list[InvoiceLine]:
    found = await session.execute(_sa.select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.line_no))
    return list(found.scalars())


async def _out(session: AsyncSession, row: Invoice) -> _s.InvoiceOut:
    lines = await _line_rows(session, row.id)
    payments = (
        await session.execute(
            _sa.select(InvoicePayment).where(InvoicePayment.invoice_id == row.id).order_by(InvoicePayment.created_at, InvoicePayment.id)
        )
    ).scalars()
    return _s.InvoiceOut(
        id=row.id,
        kind=_t.cast(_s.Kind, row.kind),
        number=row.number,
        status=row.status,
        counterparty=row.counterparty,
        counterparty_ref=row.counterparty_ref,
        currency=row.currency,
        exponent=_money.exponent(row.currency),
        issue_date=row.issue_date,
        due_date=row.due_date,
        notes=row.notes,
        subtotal_minor=row.subtotal_minor,
        tax_minor=row.tax_minor,
        total_minor=row.total_minor,
        paid_minor=row.paid_minor,
        outstanding_minor=row.total_minor - row.paid_minor,
        issue_transaction_id=row.issue_tx_id,
        void_transaction_id=row.void_tx_id,
        created_at=row.created_at,
        issued_at=row.issued_at,
        voided_at=row.voided_at,
        lines=[
            _s.LineOut(
                id=x.id,
                line_no=x.line_no,
                description=x.description,
                quantity=x.quantity,
                unit_price_minor=x.unit_price_minor,
                tax_rate=x.tax_rate,
                net_minor=x.net_minor,
                tax_minor=x.tax_minor,
                gross_minor=x.net_minor + x.tax_minor,
            )
            for x in lines
        ],
        payments=[
            _s.PaymentOut(
                id=p.id,
                amount_minor=p.amount_minor,
                paid_on=p.paid_on,
                reference=p.reference,
                ledger_transaction_id=p.ledger_tx_id,
                created_at=p.created_at,
            )
            for p in payments
        ],
    )


async def _get(session: AsyncSession, tenant: Tenant, invoice_id: _uuid.UUID, lock: bool = False) -> Invoice:
    stmt = _scoped(_sa.select(Invoice).where(Invoice.id == invoice_id), Invoice, tenant)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "invoice not found", 404)
    return row


def _write_lines(
    tenant: Tenant, invoice_id: _uuid.UUID, computed: list[tuple[_s.LineIn, _totals.LineTotal]]
) -> list[dict[str, _t.Any]]:
    rows = []
    for number, (line, total) in enumerate(computed, start=1):
        row: dict[str, _t.Any] = {
            "id": _uuid.uuid4(),
            "invoice_id": invoice_id,
            "line_no": number,
            "description": line.description,
            "quantity": line.quantity,
            "unit_price_minor": line.unit_price_minor,
            "tax_rate": line.tax_rate,
            "net_minor": total.net_minor,
            "tax_minor": total.tax_minor,
        }
        if tenant is not None:
            row["tenant_id"] = tenant
        rows.append(row)
    return rows


def _check_dates(issue: date | None, due: date | None) -> None:
    if issue is not None and due is not None and due < issue:
        raise AppError("invalid_dates", "due_date is before issue_date", 422)


# --- create / read / update (drafts) -----------------------------------------------------------


async def create_invoice(session: AsyncSession, user: _t.Any, body: _s.InvoiceCreate) -> _s.InvoiceOut:
    tenant = tenant_of(user)
    _check_currency(body.currency)
    _check_dates(body.issue_date, body.due_date)
    computed = _line_values(body.lines, body.currency)
    total = _totals.invoice_total([t for _, t in computed])
    invoice_id = _uuid.uuid4()
    values: dict[str, _t.Any] = {
        "id": invoice_id,
        "kind": body.kind,
        "status": "draft",
        "counterparty": body.counterparty,
        "counterparty_ref": body.counterparty_ref,
        "currency": body.currency,
        "issue_date": body.issue_date,
        "due_date": body.due_date,
        "notes": body.notes,
        "subtotal_minor": total.subtotal_minor,
        "tax_minor": total.tax_minor,
        "total_minor": total.total_minor,
        "paid_minor": 0,
        "created_by": getattr(user, "id", None),
    }
    if tenant is not None:
        values["tenant_id"] = tenant
    await session.execute(_sa.insert(Invoice).values(**values))
    await session.execute(_sa.insert(InvoiceLine), _write_lines(tenant, invoice_id, computed))
    await session.commit()
    return await _out(session, await _get(session, tenant, invoice_id))


async def get_invoice(session: AsyncSession, user: _t.Any, invoice_id: _uuid.UUID) -> _s.InvoiceOut:
    tenant = tenant_of(user)
    return await _out(session, await _get(session, tenant, invoice_id))


async def list_invoices(
    session: AsyncSession,
    user: _t.Any,
    limit: int,
    offset: int,
    kind: str | None,
    status: str | None,
    counterparty: str | None,
) -> tuple[list[_s.InvoiceOut], int]:
    tenant = tenant_of(user)
    base = _scoped(_sa.select(Invoice), Invoice, tenant)
    if kind is not None:
        base = base.where(Invoice.kind == kind)
    if status is not None:
        base = base.where(Invoice.status == status)
    if counterparty is not None:
        base = base.where(Invoice.counterparty == counterparty)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(base.order_by(Invoice.created_at.desc(), Invoice.id).limit(limit).offset(offset))
    return [await _out(session, r) for r in rows.scalars().all()], int(total)


async def update_invoice(session: AsyncSession, user: _t.Any, invoice_id: _uuid.UUID, body: _s.InvoiceUpdate) -> _s.InvoiceOut:
    tenant = tenant_of(user)
    row = await _get(session, tenant, invoice_id, lock=True)
    status_was = row.status  # read before any rollback expires the row
    if row.status != "draft":
        await session.rollback()
        raise AppError("invoice_immutable", f"a {status_was} invoice cannot be edited", 409)
    changes = body.model_dump(exclude_unset=True, exclude={"lines"})
    for required in ("counterparty", "currency"):
        if required in changes and changes[required] is None:
            raise AppError("invalid_field", f"{required} cannot be null", 422)
    if "currency" in changes:
        _check_currency(changes["currency"])
    currency = changes.get("currency") or row.currency
    _check_dates(changes.get("issue_date", row.issue_date), changes.get("due_date", row.due_date))
    if body.lines is not None or "currency" in changes:
        if body.lines is not None:
            new_lines = list(body.lines)
        else:
            new_lines = [
                _s.LineIn(description=x.description, quantity=x.quantity, unit_price_minor=x.unit_price_minor, tax_rate=x.tax_rate)
                for x in await _line_rows(session, row.id)
            ]
        computed = _line_values(new_lines, currency)
        total = _totals.invoice_total([t for _, t in computed])
        await session.execute(_sa.delete(InvoiceLine).where(InvoiceLine.invoice_id == row.id))
        await session.execute(_sa.insert(InvoiceLine), _write_lines(tenant, row.id, computed))
        changes.update(subtotal_minor=total.subtotal_minor, tax_minor=total.tax_minor, total_minor=total.total_minor)
    if changes:
        await session.execute(_sa.update(Invoice).where(Invoice.id == row.id).values(**changes))
    await session.commit()
    return await _out(session, await _get(session, tenant, invoice_id, lock=True))


# --- issue -------------------------------------------------------------------------------------


async def _next_number(session: AsyncSession, tenant: Tenant, kind: str) -> str:
    values: dict[str, _t.Any] = {"id": _uuid.uuid4(), "kind": kind, "last_value": 1}
    index = ["kind"]
    if tenant is not None:
        values["tenant_id"] = tenant
        index = ["tenant_id", "kind"]
    # one atomic statement: the row stays locked until COMMIT, so the next issuer waits and a rollback gives the
    # number back (no gaps, no duplicates)
    stmt = (
        _pg.insert(InvoiceCounter)
        .values(**values)
        .on_conflict_do_update(index_elements=index, set_={"last_value": InvoiceCounter.last_value + 1})
        .returning(InvoiceCounter.last_value)
    )
    sequence = int((await session.execute(stmt)).scalar_one())
    return _rules.invoice_number(_config.NUMBER_PREFIX, kind, sequence)


def _issue_lines(row: Invoice, accounts: dict[str, _t.Any]) -> list[tuple[_t.Any, int]]:
    if row.kind == "receivable":
        lines = [(accounts["party"], row.total_minor), (accounts["income"], -row.subtotal_minor)]
        if row.tax_minor:
            lines.append((accounts["tax"], -row.tax_minor))
    else:
        lines = [(accounts["party"], -row.total_minor), (accounts["income"], row.subtotal_minor)]
        if row.tax_minor:
            lines.append((accounts["tax"], row.tax_minor))
    return lines


async def _accounts(session: AsyncSession, tenant: Tenant, row: Invoice) -> dict[str, _t.Any]:
    receivable = row.kind == "receivable"
    out = {
        "party": await _post.resolve_account(
            session, tenant, _config.RECEIVABLE_ACCOUNT if receivable else _config.PAYABLE_ACCOUNT, row.currency
        ),
        "income": await _post.resolve_account(
            session, tenant, _config.REVENUE_ACCOUNT if receivable else _config.EXPENSE_ACCOUNT, row.currency
        ),
    }
    if row.tax_minor:
        out["tax"] = await _post.resolve_account(session, tenant, _config.TAX_ACCOUNT, row.currency)
    return out


def _conflict(exc: IntegrityError) -> AppError | None:
    text = str(exc.orig)
    if "does not sum to zero" in text or "at least two entries" in text:
        return AppError("unbalanced", "the posting does not balance", 500)
    if "uq_ledger_transactions_idempotency_key" in text or "uq_ledger_transactions_reverses_id" in text:
        return AppError("conflict", "this invoice was already posted", 409)
    if "immutable" in text or "cannot change" in text:
        return AppError("invoice_immutable", "this invoice can no longer be changed", 409)
    return None


async def issue_invoice(session: AsyncSession, user: _t.Any, invoice_id: _uuid.UUID) -> _s.InvoiceOut:
    tenant = tenant_of(user)
    row = await _get(session, tenant, invoice_id, lock=True)
    status_was = row.status  # read before any rollback expires the row
    if not _rules.can_transition(row.status, "issued"):
        await session.rollback()
        raise AppError("invalid_transition", f"a {status_was} invoice cannot be issued", 409)
    if row.total_minor <= 0:
        await session.rollback()
        raise AppError("empty_invoice", "an invoice with a zero total cannot be issued", 422)
    try:
        accounts = await _accounts(session, tenant, row)
        number = await _next_number(session, tenant, row.kind)
        issue = row.issue_date or _today()
        due = row.due_date or issue + timedelta(days=_config.PAYMENT_TERMS_DAYS)
        if due < issue:
            raise AppError("invalid_dates", "due_date is before issue_date", 422)
        tx_id = await _post.stage(
            session,
            tenant,
            user,
            key=f"invoice:{row.id}:issue",
            description=f"Invoice {number} ({row.kind}) {row.counterparty}",
            reference=number,
            lines=_issue_lines(row, accounts),
        )
        await session.execute(
            _sa.update(Invoice)
            .where(Invoice.id == row.id)
            .values(status="issued", number=number, issue_date=issue, due_date=due, issue_tx_id=tx_id, issued_at=_models_base.utcnow())
        )
        await session.commit()  # the invoice, its number, the counter and the ledger transaction: all or nothing
    except AppError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        error = _conflict(exc)
        if error is not None:
            raise error from exc
        raise
    return await _out(session, await _get(session, tenant, invoice_id, lock=True))


# --- payments ----------------------------------------------------------------------------------


async def _payment_by_key(session: AsyncSession, tenant: Tenant, key: str) -> InvoicePayment | None:
    stmt = _scoped(_sa.select(InvoicePayment).where(InvoicePayment.idempotency_key == key), InvoicePayment, tenant)
    return (await session.execute(stmt)).scalar_one_or_none()


async def record_payment(
    session: AsyncSession, user: _t.Any, invoice_id: _uuid.UUID, body: _s.PaymentIn
) -> tuple[_s.InvoiceOut, bool]:
    tenant = tenant_of(user)
    paid_on = body.paid_on or _today()
    fingerprint = _fingerprint("payment", str(invoice_id), body.amount_minor, body.paid_on, body.reference)  # the raw value: a retry after midnight still replays

    async def replay() -> bool:
        existing = await _payment_by_key(session, tenant, body.idempotency_key)
        if existing is None:
            return False
        if existing.request_hash != fingerprint:
            raise AppError("idempotency_conflict", "this idempotency_key was already used for a different payment", 409)
        return True

    if await replay():
        return await _out(session, await _get(session, tenant, invoice_id)), True
    row = await _get(session, tenant, invoice_id, lock=True)
    status_was = row.status  # read before any rollback expires the row
    if await replay():  # a parallel request with the same key finished while we waited for the lock
        await session.rollback()
        return await _out(session, await _get(session, tenant, invoice_id)), True
    if row.status not in ("issued", "partially_paid"):
        await session.rollback()
        raise AppError("invalid_transition", f"a {status_was} invoice cannot take a payment", 409)
    outstanding = row.total_minor - row.paid_minor
    if body.amount_minor > outstanding:
        await session.rollback()
        raise AppError(
            "overpayment",
            "the payment is more than the amount outstanding",
            422,
            [{"outstanding_minor": outstanding, "amount_minor": body.amount_minor}],
        )
    try:
        receivable = row.kind == "receivable"
        party = await _post.resolve_account(
            session, tenant, _config.RECEIVABLE_ACCOUNT if receivable else _config.PAYABLE_ACCOUNT, row.currency
        )
        cash = await _post.resolve_account(session, tenant, _config.CASH_ACCOUNT, row.currency)
        payment_id = _uuid.uuid4()
        amount = body.amount_minor
        lines = [(cash, amount), (party, -amount)] if receivable else [(party, amount), (cash, -amount)]
        tx_id = await _post.stage(
            session,
            tenant,
            user,
            key=f"payment:{payment_id}",
            description=f"Payment of invoice {row.number}",
            reference=row.number,
            lines=lines,
        )
        values: dict[str, _t.Any] = {
            "id": payment_id,
            "invoice_id": row.id,
            "idempotency_key": body.idempotency_key,
            "request_hash": fingerprint,
            "amount_minor": amount,
            "paid_on": paid_on,
            "reference": body.reference,
            "ledger_tx_id": tx_id,
            "created_by": getattr(user, "id", None),
        }
        if tenant is not None:
            values["tenant_id"] = tenant
        await session.execute(_sa.insert(InvoicePayment).values(**values))
        paid = row.paid_minor + amount
        status = "paid" if paid == row.total_minor else "partially_paid"
        await session.execute(_sa.update(Invoice).where(Invoice.id == row.id).values(paid_minor=paid, status=status))
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        if "uq_invoice_payments_idempotency_key" in str(exc.orig):
            raise AppError("idempotency_conflict", "this idempotency_key was already used", 409) from exc
        error = _conflict(exc)
        if error is not None:
            raise error from exc
        raise
    return await _out(session, await _get(session, tenant, invoice_id, lock=True)), False


# --- void --------------------------------------------------------------------------------------


async def void_invoice(
    session: AsyncSession, user: _t.Any, invoice_id: _uuid.UUID, body: _s.VoidIn
) -> tuple[_s.InvoiceOut, bool]:
    tenant = tenant_of(user)
    row = await _get(session, tenant, invoice_id, lock=True)
    status_was = row.status  # read before any rollback expires the row
    if row.status == "void":
        await session.rollback()
        return await _out(session, await _get(session, tenant, invoice_id)), True
    if status_was == "partially_paid":
        await session.rollback()
        raise AppError("has_payments", "an invoice with payments cannot be voided", 409)
    if not _rules.can_transition(status_was, "void"):
        await session.rollback()
        raise AppError("invalid_transition", f"a {status_was} invoice cannot be voided", 409)
    values: dict[str, _t.Any] = {"status": "void", "voided_at": _models_base.utcnow()}
    try:
        if row.issue_tx_id is not None:
            lines = await _post.reversal_lines(session, row.issue_tx_id)
            values["void_tx_id"] = await _post.stage(
                session,
                tenant,
                user,
                key=f"invoice:{row.id}:void",
                description=body.reason or f"Void of invoice {row.number}",
                reference=row.number,
                lines=lines,
                reverses_id=row.issue_tx_id,
            )
        await session.execute(_sa.update(Invoice).where(Invoice.id == row.id).values(**values))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        error = _conflict(exc)
        if error is not None:
            raise error from exc
        raise
    return await _out(session, await _get(session, tenant, invoice_id, lock=True)), False


# --- aging -------------------------------------------------------------------------------------


async def aging(session: AsyncSession, user: _t.Any, kind: str, as_of: date | None) -> _s.AgingOut:
    tenant = tenant_of(user)
    day = as_of or _today()
    outstanding = _sa.func.sum(Invoice.total_minor - Invoice.paid_minor)
    stmt = (
        _sa.select(Invoice.currency, Invoice.due_date, outstanding, _sa.func.count())
        .where(Invoice.kind == kind, Invoice.status.in_(("issued", "partially_paid")))
        .group_by(Invoice.currency, Invoice.due_date)
    )
    rows = [
        (cur, due, int(amount), int(count)) for cur, due, amount, count in (await session.execute(_scoped(stmt, Invoice, tenant))).all()
    ]
    return _s.AgingOut(
        kind=_t.cast(_s.Kind, kind),
        as_of=day,
        bucket_days=list(_config.AGING_BUCKETS_DAYS),
        currencies=[_s.AgingCurrencyOut(**c) for c in _rules.age(rows, day, _config.AGING_BUCKETS_DAYS)],  # type: ignore[arg-type]
    )
