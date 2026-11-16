"""Reconciliation service (generated). The rules, in one place.

* A run belongs to ONE ledger account. Statement lines are imported with the run (idempotent by the run's
  `idempotency_key`: the same key and body returns the first result, the same key with another body is a 409);
  more lines can be appended while the run is open (a line with a known external_id and the same content is
  skipped, with other content it is a 409).
* Amounts have the same sign as the account's ledger entries (positive = debit side). Integers only.
* Every write that pairs or un-pairs takes a row lock on the ledger account first, so parallel matchers of
  one account run one after the other; UNIQUE(entry_id) / UNIQUE(line_id) on the match table is the backstop.
* A run is closed once: the summary (integers) is stored with it, lines and matches are frozen by the database.
"""

import hashlib
import json
import typing as _t
import uuid as _uuid
from datetime import date

import sqlalchemy as _sa
from sqlalchemy.dialects import postgresql as _pg
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import _base as _models_base
from app.money.ledger.models import LedgerAccount, LedgerEntry, LedgerTransaction
from app.money.reconciliation import config as _config
from app.money.reconciliation import matcher as _matcher
from app.money.reconciliation import schemas as _s
from app.money.reconciliation.models import (
    ReconciliationEvent,
    ReconciliationLine,
    ReconciliationMatch,
    ReconciliationRun,
)

Tenant = _uuid.UUID | None


def tenant_of(user: _t.Any) -> Tenant:
    if not _config.MULTI_TENANT:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise AppError("forbidden", "reconciliation needs a caller that belongs to a tenant", 403)
    return _t.cast(_uuid.UUID, tenant)


def _scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"), sort_keys=True, default=str).encode()).hexdigest()


def _line_key(line: _s.LineIn) -> list[object]:
    return [line.external_id, line.date.isoformat(), line.amount_minor, line.currency, line.reference]


def _entry_day() -> _t.Any:
    return _sa.cast(_sa.func.timezone("UTC", LedgerTransaction.posted_at), _sa.Date)


def _line_out(row: ReconciliationLine) -> _s.LineOut:
    return _s.LineOut(
        id=row.id,
        line_no=row.line_no,
        external_id=row.external_id,
        date=row.line_date,
        amount_minor=row.amount,
        currency=row.currency,
        reference=row.reference,
    )


def _match_out(row: ReconciliationMatch) -> _s.MatchOut:
    return _s.MatchOut(
        id=row.id,
        line_id=row.line_id,
        entry_id=row.entry_id,
        method=row.method,
        diff_minor=row.diff_minor,
        matched_at=row.matched_at,
    )


async def _event(
    session: AsyncSession,
    tenant: Tenant,
    user: _t.Any,
    run_id: _uuid.UUID,
    action: str,
    line_id: _uuid.UUID | None = None,
    entry_id: _uuid.UUID | None = None,
    method: str | None = None,
) -> None:
    values: dict[str, _t.Any] = {
        "id": _uuid.uuid4(),
        "run_id": run_id,
        "action": action,
        "line_id": line_id,
        "entry_id": entry_id,
        "method": method,
        "actor": getattr(user, "id", None),
    }
    if tenant is not None:
        values["tenant_id"] = tenant
    await session.execute(_sa.insert(ReconciliationEvent).values(**values))


async def _get_run(session: AsyncSession, tenant: Tenant, run_id: _uuid.UUID, lock: bool = False) -> ReconciliationRun:
    stmt = _scoped(_sa.select(ReconciliationRun).where(ReconciliationRun.id == run_id), ReconciliationRun, tenant)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "reconciliation run not found", 404)
    return row


async def _lock_account(session: AsyncSession, tenant: Tenant, account_id: _uuid.UUID) -> None:
    stmt = _scoped(_sa.select(LedgerAccount.id).where(LedgerAccount.id == account_id), LedgerAccount, tenant)
    # FOR NO KEY UPDATE: serialises matchers, but does not block ledger postings (their FK takes FOR KEY SHARE)
    await session.execute(stmt.with_for_update(key_share=True))


def _open_only(run: ReconciliationRun) -> None:
    if run.status != "open":
        raise AppError("run_closed", "this reconciliation run is closed", 409)


async def _counts(session: AsyncSession, run_id: _uuid.UUID) -> tuple[int, int]:
    lines = (await session.execute(_sa.select(_sa.func.count()).where(ReconciliationLine.run_id == run_id))).scalar_one()
    matched = (await session.execute(_sa.select(_sa.func.count()).where(ReconciliationMatch.run_id == run_id))).scalar_one()
    return int(lines), int(matched)


async def _run_out(session: AsyncSession, run: ReconciliationRun) -> _s.RunOut:
    line_count, matched_count = await _counts(session, run.id)
    return _s.RunOut(
        id=run.id,
        account_id=run.account_id,
        currency=run.currency,
        name=run.name,
        period_start=run.period_start,
        period_end=run.period_end,
        status=run.status,
        line_count=line_count,
        matched_count=matched_count,
        created_at=run.created_at,
        closed_at=run.closed_at,
        summary=_s.SummaryOut(**run.summary) if run.summary else None,
    )


def _check_lines(lines: _t.Sequence[_s.LineIn], currency: str) -> None:
    seen: set[str] = set()
    for line in lines:
        if line.amount_minor == 0:
            raise AppError("invalid_line", f"line {line.external_id!r}: an amount cannot be zero", 422)
        if line.currency != currency:
            raise AppError(
                "currency_mismatch",
                f"line {line.external_id!r} is in {line.currency}, the account is in {currency}",
                422,
            )
        if line.external_id in seen:
            raise AppError("duplicate_line", f"external_id {line.external_id!r} appears twice", 422)
        seen.add(line.external_id)


def _line_rows(tenant: Tenant, run_id: _uuid.UUID, lines: _t.Sequence[_s.LineIn], first_no: int) -> list[dict[str, _t.Any]]:
    rows = []
    for number, line in enumerate(lines, start=first_no):
        row: dict[str, _t.Any] = {
            "id": _uuid.uuid4(),
            "run_id": run_id,
            "line_no": number,
            "external_id": line.external_id,
            "line_date": line.date,
            "amount": line.amount_minor,
            "currency": line.currency,
            "reference": line.reference,
        }
        if tenant is not None:
            row["tenant_id"] = tenant
        rows.append(row)
    return rows


# --- runs --------------------------------------------------------------------------------------


async def import_run(session: AsyncSession, user: _t.Any, body: _s.RunCreate) -> tuple[_s.RunOut, bool]:
    tenant = tenant_of(user)
    if body.period_start and body.period_end and body.period_start > body.period_end:
        raise AppError("invalid_period", "period_start is after period_end", 422)
    fingerprint = _fingerprint(
        "run", str(body.account_id), body.name, body.period_start, body.period_end, [_line_key(x) for x in body.lines]
    )

    async def replay() -> _s.RunOut | None:
        stmt = _scoped(
            _sa.select(ReconciliationRun).where(ReconciliationRun.idempotency_key == body.idempotency_key),
            ReconciliationRun,
            tenant,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            return None
        if existing.request_hash != fingerprint:
            raise AppError("idempotency_conflict", "this idempotency_key was already used for a different statement", 409)
        return await _run_out(session, existing)

    first = await replay()
    if first is not None:
        return first, True
    account = (
        await session.execute(_scoped(_sa.select(LedgerAccount).where(LedgerAccount.id == body.account_id), LedgerAccount, tenant))
    ).scalar_one_or_none()
    if account is None:
        raise AppError("unknown_account", "the ledger account does not exist", 422)
    _check_lines(body.lines, account.currency)
    run_id = _uuid.uuid4()
    header: dict[str, _t.Any] = {
        "id": run_id,
        "idempotency_key": body.idempotency_key,
        "request_hash": fingerprint,
        "account_id": account.id,
        "currency": account.currency,
        "name": body.name,
        "period_start": body.period_start,
        "period_end": body.period_end,
        "status": "open",
        "created_by": getattr(user, "id", None),
    }
    index = ["idempotency_key"]
    if tenant is not None:
        header["tenant_id"] = tenant
        index = ["tenant_id", "idempotency_key"]
    inserted = await session.execute(
        _pg.insert(ReconciliationRun).values(**header).on_conflict_do_nothing(index_elements=index).returning(ReconciliationRun.id)
    )
    if inserted.scalar_one_or_none() is None:  # a parallel import of the same key won: read its result
        await session.rollback()
        again = await replay()
        if again is None:
            raise AppError("conflict", "could not import, retry", 409)
        return again, True
    await session.execute(_sa.insert(ReconciliationLine), _line_rows(tenant, run_id, body.lines, 1))
    await _event(session, tenant, user, run_id, "import")
    await session.commit()
    return await _run_out(session, await _get_run(session, tenant, run_id)), False


async def list_runs(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, status: str | None
) -> tuple[list[_s.RunOut], int]:
    tenant = tenant_of(user)
    base = _scoped(_sa.select(ReconciliationRun), ReconciliationRun, tenant)
    if status is not None:
        base = base.where(ReconciliationRun.status == status)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(base.order_by(ReconciliationRun.created_at.desc(), ReconciliationRun.id).limit(limit).offset(offset))
    return [await _run_out(session, r) for r in rows.scalars().all()], int(total)


async def get_run(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID) -> _s.RunOut:
    tenant = tenant_of(user)
    return await _run_out(session, await _get_run(session, tenant, run_id))


async def add_lines(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID, body: _s.LinesAdd) -> _s.LinesAddedOut:
    tenant = tenant_of(user)
    run = await _get_run(session, tenant, run_id, lock=True)
    _open_only(run)
    _check_lines(body.lines, run.currency)
    found = await session.execute(select_lines(run_id))
    known = {r.external_id: r for r in found.scalars()}
    fresh: list[_s.LineIn] = []
    skipped = 0
    for line in body.lines:
        old = known.get(line.external_id)
        if old is None:
            fresh.append(line)
        elif (old.line_date, old.amount, old.currency, old.reference) == (line.date, line.amount_minor, line.currency, line.reference):
            skipped += 1
        else:
            await session.rollback()
            raise AppError("line_conflict", f"external_id {line.external_id!r} was imported with different content", 409)
    if len(known) + len(fresh) > _config.MAX_LINES:
        await session.rollback()
        raise AppError("too_many_lines", f"a run holds at most {_config.MAX_LINES} statement lines", 422)
    if fresh:
        await session.execute(_sa.insert(ReconciliationLine), _line_rows(tenant, run_id, fresh, len(known) + 1))
        await _event(session, tenant, user, run_id, "import")
    await session.commit()
    return _s.LinesAddedOut(added=len(fresh), skipped=skipped, line_count=len(known) + len(fresh))


def select_lines(run_id: _uuid.UUID) -> _t.Any:
    return _sa.select(ReconciliationLine).where(ReconciliationLine.run_id == run_id).order_by(ReconciliationLine.line_no)


# --- loading the picture -----------------------------------------------------------------------


async def _candidate_entries(
    session: AsyncSession, tenant: Tenant, run: ReconciliationRun
) -> tuple[list[tuple[LedgerEntry, LedgerTransaction, date]], bool]:
    """Ledger entries of the run's account (inside the period when given) that are not matched anywhere."""
    day = _entry_day()
    stmt = (
        _sa.select(LedgerEntry, LedgerTransaction, day.label("day"))
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(LedgerEntry.account_id == run.account_id)
        .where(~_sa.exists().where(ReconciliationMatch.entry_id == LedgerEntry.id))
    )
    stmt = _scoped(stmt, LedgerEntry, tenant)
    if run.period_start is not None:
        stmt = stmt.where(day >= run.period_start)
    if run.period_end is not None:
        stmt = stmt.where(day <= run.period_end)
    rows = (
        await session.execute(stmt.order_by(LedgerTransaction.posted_at, LedgerEntry.id).limit(_config.ENTRY_CAP + 1))
    ).all()
    truncated = len(rows) > _config.ENTRY_CAP
    return [(e, t, d) for e, t, d in rows[: _config.ENTRY_CAP]], truncated


def _entry_ref(entry: LedgerEntry, tx: LedgerTransaction, day: date) -> _s.EntryRefOut:
    return _s.EntryRefOut(
        id=entry.id,
        transaction_id=entry.transaction_id,
        date=day,
        amount_minor=entry.amount,
        reference=tx.reference,
        description=tx.description,
    )


async def _matched_pairs(session: AsyncSession, tenant: Tenant, run: ReconciliationRun) -> list[_s.MatchedPairOut]:
    day = _entry_day()
    stmt = (
        _sa.select(ReconciliationMatch, ReconciliationLine, LedgerEntry, LedgerTransaction, day.label("day"))
        .join(ReconciliationLine, ReconciliationLine.id == ReconciliationMatch.line_id)
        .join(LedgerEntry, LedgerEntry.id == ReconciliationMatch.entry_id)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(ReconciliationMatch.run_id == run.id)
        .order_by(ReconciliationLine.line_no)
    )
    stmt = _scoped(stmt, ReconciliationMatch, tenant)
    return [
        _s.MatchedPairOut(match=_match_out(m), line=_line_out(line), entry=_entry_ref(e, t, d))
        for m, line, e, t, d in (await session.execute(stmt)).all()
    ]


def _summary(
    run: ReconciliationRun,
    lines: _t.Sequence[_s.LineOut],
    matched: _t.Sequence[_s.MatchedPairOut],
    unmatched_lines: _t.Sequence[_s.LineOut],
    unmatched_entries: _t.Sequence[_s.EntryRefOut],
) -> _s.SummaryOut:
    statement_total = sum(x.amount_minor for x in lines)
    matched_lines = sum(p.line.amount_minor for p in matched)
    matched_entries = sum(p.entry.amount_minor for p in matched)
    unmatched_lines_sum = sum(x.amount_minor for x in unmatched_lines)
    unmatched_entries_sum = sum(x.amount_minor for x in unmatched_entries)
    matched_diff = matched_lines - matched_entries
    return _s.SummaryOut(
        currency=run.currency,
        line_count=len(lines),
        matched_count=len(matched),
        unmatched_line_count=len(unmatched_lines),
        unmatched_entry_count=len(unmatched_entries),
        statement_total_minor=statement_total,
        matched_lines_minor=matched_lines,
        matched_entries_minor=matched_entries,
        matched_diff_minor=matched_diff,
        unmatched_lines_minor=unmatched_lines_sum,
        unmatched_entries_minor=unmatched_entries_sum,
        difference_minor=matched_diff + unmatched_lines_sum - unmatched_entries_sum,
    )


async def _results(session: AsyncSession, tenant: Tenant, run: ReconciliationRun) -> _s.ResultsOut:
    lines = [_line_out(x) for x in (await session.execute(select_lines(run.id))).scalars()]
    matched = await _matched_pairs(session, tenant, run)
    matched_lines = {p.line.id for p in matched}
    unmatched_lines = [x for x in lines if x.id not in matched_lines]
    candidates, truncated = await _candidate_entries(session, tenant, run)
    unmatched_entries = [_entry_ref(e, t, d) for e, t, d in candidates]
    return _s.ResultsOut(
        run=await _run_out(session, run),
        matched=matched,
        unmatched_lines=unmatched_lines,
        unmatched_entries=unmatched_entries,
        entries_truncated=truncated,
        summary=_summary(run, lines, matched, unmatched_lines, unmatched_entries),
    )


async def results(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID) -> _s.ResultsOut:
    tenant = tenant_of(user)
    return await _results(session, tenant, await _get_run(session, tenant, run_id))


# --- matching ----------------------------------------------------------------------------------


def _conflict(exc: IntegrityError) -> AppError | None:
    text = str(exc.orig)
    if "uq_reconciliation_matches_entry_id" in text:
        return AppError("entry_already_matched", "this ledger entry is already matched", 409)
    if "uq_reconciliation_matches_line_id" in text:
        return AppError("line_already_matched", "this statement line is already matched", 409)
    if "is closed" in text:
        return AppError("run_closed", "this reconciliation run is closed", 409)
    return None


async def auto_match(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID) -> _s.AutoMatchOut:
    tenant = tenant_of(user)
    run = await _get_run(session, tenant, run_id, lock=True)
    _open_only(run)
    await _lock_account(session, tenant, run.account_id)
    lines = [x for x in (await session.execute(select_lines(run_id))).scalars()]
    already = set((await session.execute(_sa.select(ReconciliationMatch.line_id).where(ReconciliationMatch.run_id == run_id))).scalars())
    open_lines = [x for x in lines if x.id not in already]
    candidates, _truncated = await _candidate_entries(session, tenant, run)
    pairs = _matcher.match(
        [_matcher.Item(str(x.id), x.line_date, x.amount, x.reference, x.line_no) for x in open_lines],
        [_matcher.Item(str(e.id), d, e.amount, t.reference, n) for n, (e, t, d) in enumerate(candidates)],
        _config.TOLERANCE_MINOR,
    )
    rows = []
    for pair in pairs:
        row: dict[str, _t.Any] = {
            "id": _uuid.uuid4(),
            "run_id": run_id,
            "line_id": _uuid.UUID(pair.line_id),
            "entry_id": _uuid.UUID(pair.entry_id),
            "method": pair.method,
            "diff_minor": pair.diff_minor,
            "matched_by": getattr(user, "id", None),
        }
        if tenant is not None:
            row["tenant_id"] = tenant
        rows.append(row)
    try:
        if rows:
            await session.execute(_sa.insert(ReconciliationMatch), rows)
            for pair in pairs:
                await _event(session, tenant, user, run_id, "match", _uuid.UUID(pair.line_id), _uuid.UUID(pair.entry_id), pair.method)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        error = _conflict(exc)
        if error is not None:
            raise error from exc
        raise
    total = len(already) + len(pairs)
    return _s.AutoMatchOut(new_matches=len(pairs), matched_count=total, unmatched_line_count=len(lines) - total)


async def manual_match(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID, body: _s.ManualMatchIn) -> _s.MatchOut:
    tenant = tenant_of(user)
    run = await _get_run(session, tenant, run_id, lock=True)
    _open_only(run)
    await _lock_account(session, tenant, run.account_id)
    line = (
        await session.execute(
            _sa.select(ReconciliationLine).where(ReconciliationLine.id == body.line_id, ReconciliationLine.run_id == run_id)
        )
    ).scalar_one_or_none()
    if line is None:
        raise AppError("not_found", "statement line not found in this run", 404)
    entry = (
        await session.execute(
            _scoped(
                _sa.select(LedgerEntry).where(LedgerEntry.id == body.entry_id, LedgerEntry.account_id == run.account_id),
                LedgerEntry,
                tenant,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise AppError("not_found", "ledger entry not found on this run's account", 404)
    row: dict[str, _t.Any] = {
        "id": _uuid.uuid4(),
        "run_id": run_id,
        "line_id": line.id,
        "entry_id": entry.id,
        "method": "manual",
        "diff_minor": line.amount - entry.amount,
        "matched_by": getattr(user, "id", None),
    }
    if tenant is not None:
        row["tenant_id"] = tenant
    try:
        await session.execute(_sa.insert(ReconciliationMatch), [row])
        await _event(session, tenant, user, run_id, "match", line.id, entry.id, "manual")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        error = _conflict(exc)
        if error is not None:
            raise error from exc
        raise
    stored = (await session.execute(_sa.select(ReconciliationMatch).where(ReconciliationMatch.id == row["id"]))).scalar_one()
    return _match_out(stored)


async def unmatch(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID, match_id: _uuid.UUID) -> _s.MatchOut:
    tenant = tenant_of(user)
    run = await _get_run(session, tenant, run_id, lock=True)
    _open_only(run)
    await _lock_account(session, tenant, run.account_id)
    found = (
        await session.execute(
            _sa.select(ReconciliationMatch).where(ReconciliationMatch.id == match_id, ReconciliationMatch.run_id == run_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise AppError("not_found", "match not found in this run", 404)
    out = _match_out(found)
    await session.execute(_sa.delete(ReconciliationMatch).where(ReconciliationMatch.id == match_id))
    await _event(session, tenant, user, run_id, "unmatch", found.line_id, found.entry_id, found.method)
    await session.commit()
    return out


async def close_run(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID) -> tuple[_s.RunOut, bool]:
    tenant = tenant_of(user)
    run = await _get_run(session, tenant, run_id, lock=True)
    if run.status == "closed":
        return await _run_out(session, run), True
    await _lock_account(session, tenant, run.account_id)
    picture = await _results(session, tenant, run)
    if picture.entries_truncated:
        raise AppError(
            "entries_truncated",
            "too many unmatched ledger entries to close this run; narrow period_start / period_end",
            422,
        )
    run.status = "closed"
    run.summary = picture.summary.model_dump(mode="json")
    run.closed_by = getattr(user, "id", None)
    run.closed_at = _models_base.utcnow()
    await _event(session, tenant, user, run_id, "close")
    await session.commit()
    return await _run_out(session, run), False
