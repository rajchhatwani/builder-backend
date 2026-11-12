"""Payouts service (generated, pack money.invoicing with `payouts`). A payout takes a fully paid RECEIVABLE
invoice and splits its net amount (before tax) between the platform and a seller:

    commission = the platform's share (COMMISSION_BP basis points), seller = the rest; both come from ONE
    largest-remainder allocation (app/money/currency.py: allocate), so commission + seller == net exactly.

    split ledger transaction:  debit revenue (net), credit commission account, credit seller payable
    payout ledger transaction: debit seller payable, credit cash/bank (the bank statement shows this amount)

Both post in the same database transaction as the payout row. `idempotency_key` makes a call safe to repeat
(parallel calls of one key create exactly one payout); an invoice is paid out once (UNIQUE(invoice_id))."""

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
from app.money.invoicing import config as _config
from app.money.invoicing import posting as _post
from app.money.invoicing import schemas as _s
from app.money.invoicing.models import Invoice, MoneyPayout

Tenant = _uuid.UUID | None


def tenant_of(user: _t.Any) -> Tenant:
    return _post.tenant_of(user, _config.MULTI_TENANT)


def _scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return _post.scoped(stmt, model, tenant)


def split(net_minor: int, commission_bp: int) -> tuple[int, int]:
    """(commission, seller) for a net amount: largest-remainder allocation over [bp, 10000 - bp]."""
    commission, seller = _money.allocate(net_minor, [commission_bp, 10_000 - commission_bp])
    return commission, seller


def _out(row: MoneyPayout) -> _s.PayoutOut:
    return _s.PayoutOut(
        id=row.id,
        invoice_id=row.invoice_id,
        seller=row.seller,
        currency=row.currency,
        gross_minor=row.gross_minor,
        commission_bp=row.commission_bp,
        commission_minor=row.commission_minor,
        seller_minor=row.seller_minor,
        split_transaction_id=row.split_tx_id,
        payout_transaction_id=row.payout_tx_id,
        created_at=row.created_at,
    )


async def _by_key(session: AsyncSession, tenant: Tenant, key: str) -> MoneyPayout | None:
    stmt = _scoped(_sa.select(MoneyPayout).where(MoneyPayout.idempotency_key == key), MoneyPayout, tenant)
    return (await session.execute(stmt)).scalar_one_or_none()


async def run_payout(session: AsyncSession, user: _t.Any, body: _s.PayoutRunIn) -> tuple[_s.PayoutOut, bool]:
    tenant = tenant_of(user)
    fingerprint = hashlib.sha256(
        json.dumps(["payout", str(body.invoice_id), body.seller], separators=(",", ":")).encode()
    ).hexdigest()

    async def replay() -> _s.PayoutOut | None:
        existing = await _by_key(session, tenant, body.idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != fingerprint:
            raise AppError("idempotency_conflict", "this idempotency_key was already used for a different payout", 409)
        return _out(existing)

    first = await replay()
    if first is not None:
        return first, True
    invoice = (
        await session.execute(_scoped(_sa.select(Invoice).where(Invoice.id == body.invoice_id), Invoice, tenant))
    ).scalar_one_or_none()
    if invoice is None:
        raise AppError("not_found", "invoice not found", 404)
    if invoice.kind != "receivable":
        raise AppError("invalid_invoice", "only a receivable invoice can be paid out", 409)
    if invoice.status != "paid":
        raise AppError("invoice_not_paid", "an invoice is paid out once it is fully paid", 409)
    if invoice.subtotal_minor <= 0:
        raise AppError("nothing_to_pay_out", "the invoice has no net amount", 409)
    commission, seller = split(invoice.subtotal_minor, _config.COMMISSION_BP)
    payout_id, split_tx, payout_tx = _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4()
    values: dict[str, _t.Any] = {
        "id": payout_id,
        "idempotency_key": body.idempotency_key,
        "request_hash": fingerprint,
        "invoice_id": invoice.id,
        "seller": body.seller,
        "currency": invoice.currency,
        "gross_minor": invoice.subtotal_minor,
        "commission_bp": _config.COMMISSION_BP,
        "commission_minor": commission,
        "seller_minor": seller,
        "split_tx_id": split_tx,
        "payout_tx_id": payout_tx if seller > 0 else None,
        "created_by": getattr(user, "id", None),
    }
    if tenant is not None:
        values["tenant_id"] = tenant
    try:
        # FIRST statement of the transaction: a parallel call of the same key waits here for the winner's COMMIT,
        # then does nothing and reads the winner's row (replay)
        inserted = await session.execute(
            _pg.insert(MoneyPayout).values(**values).on_conflict_do_nothing().returning(MoneyPayout.id)
        )
        if inserted.scalar_one_or_none() is None:
            await session.rollback()
            again = await replay()
            if again is not None:
                return again, True
            raise AppError("already_paid_out", "this invoice has already been paid out", 409)
        currency = invoice.currency
        revenue = await _post.resolve_account(session, tenant, _config.REVENUE_ACCOUNT, currency)
        cash = await _post.resolve_account(session, tenant, _config.CASH_ACCOUNT, currency)
        commission_account = await _post.resolve_account(session, tenant, _config.COMMISSION_ACCOUNT, currency)
        payable = await _post.resolve_account(session, tenant, _config.SELLER_PAYABLE_ACCOUNT, currency)
        await _post.stage(
            session,
            tenant,
            user,
            key=f"payout:{payout_id}:split",
            description=f"Split of invoice {invoice.number} for {body.seller}",
            reference=invoice.number,
            lines=[(revenue, invoice.subtotal_minor), (commission_account, -commission), (payable, -seller)],
            tx_id=split_tx,
        )
        if seller > 0:
            await _post.stage(
                session,
                tenant,
                user,
                key=f"payout:{payout_id}:pay",
                description=f"Payout to {body.seller} for invoice {invoice.number}",
                reference=f"PAYOUT-{payout_id}",
                lines=[(payable, seller), (cash, -seller)],
                tx_id=payout_tx,
            )
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        if "does not sum to zero" in str(exc.orig):
            raise AppError("unbalanced", "the payout does not balance", 500) from exc
        raise
    stored = (await session.execute(_sa.select(MoneyPayout).where(MoneyPayout.id == payout_id))).scalar_one()
    return _out(stored), False


async def list_payouts(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, seller: str | None, invoice_id: _uuid.UUID | None
) -> tuple[list[_s.PayoutOut], int]:
    tenant = tenant_of(user)
    base = _scoped(_sa.select(MoneyPayout), MoneyPayout, tenant)
    if seller is not None:
        base = base.where(MoneyPayout.seller == seller)
    if invoice_id is not None:
        base = base.where(MoneyPayout.invoice_id == invoice_id)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(base.order_by(MoneyPayout.created_at.desc(), MoneyPayout.id).limit(limit).offset(offset))
    return [_out(r) for r in rows.scalars()], int(total)


async def get_payout(session: AsyncSession, user: _t.Any, payout_id: _uuid.UUID) -> _s.PayoutOut:
    tenant = tenant_of(user)
    row = (await session.execute(_scoped(_sa.select(MoneyPayout).where(MoneyPayout.id == payout_id), MoneyPayout, tenant))).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "payout not found", 404)
    return _out(row)


async def totals(session: AsyncSession, user: _t.Any, seller: str | None) -> list[_s.PayoutTotalOut]:
    tenant = tenant_of(user)
    stmt = _sa.select(
        MoneyPayout.seller,
        MoneyPayout.currency,
        _sa.func.count(),
        _sa.func.sum(MoneyPayout.gross_minor),
        _sa.func.sum(MoneyPayout.commission_minor),
        _sa.func.sum(MoneyPayout.seller_minor),
    ).group_by(MoneyPayout.seller, MoneyPayout.currency)
    stmt = _scoped(stmt, MoneyPayout, tenant)
    if seller is not None:
        stmt = stmt.where(MoneyPayout.seller == seller)
    return [
        _s.PayoutTotalOut(
            seller=s, currency=c, count=int(n), gross_minor=int(g), commission_minor=int(k), seller_minor=int(x)
        )
        for s, c, n, g, k, x in (await session.execute(stmt.order_by(MoneyPayout.seller, MoneyPayout.currency))).all()
    ]
