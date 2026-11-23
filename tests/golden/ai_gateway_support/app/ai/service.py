"""AI gateway service (generated). The rules, in one place.

* A call is routed by STAGE (config.STAGES: provider, model, output cap, optional fallback model).
* Cost is integer micro-USD: ceil(tokens * price_per_million / 1_000_000) per direction (config.PRICES, UNVERIFIED).
* The WORST-CASE cost (estimated input + the output cap, on the dearest of model and fallback) is RESERVED against the
  period budget in one transaction while the period row is locked (FOR UPDATE), BEFORE the provider is called. The
  check and the reservation are one step, so parallel calls queue on the lock and `spent + reserved` never exceeds
  the budget (-> 429 budget_exceeded, nothing recorded). A worst case above the per-call cap is refused first
  (-> 422 per_call_cap_exceeded).
* After the provider answered the real cost (never more than the reservation) is settled; on a provider error the
  reservation is released and the call stays in the ledger with status `error`. Every call that passed the budget
  check is a ledger row (ai_calls).
* Idempotent per (caller, idempotency_key): the same key and body is ONE call, also when sent in parallel (the second
  request waits for the first and returns its result). A call that ended in `error` does not occupy the key.
* The provider call has a hard timeout (PROVIDER_TIMEOUT_SECONDS, below the stale window). A cancellation (client
  disconnect) or any other failure between reserve and settle releases the reservation at once from an independent
  session (error_code `cancelled`), then re-raises.
* A reservation older than STALE_RESERVATION_SECONDS (a crashed worker) is released as `abandoned` the next time the
  period is locked.
* ZERO_RETENTION: prompt and output text are never written to the database, only the hash and the token counts.
"""

import asyncio
import hashlib
import hmac
import json
import time
import typing as _t
import uuid as _uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as _sa
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import config as _config
from app.ai import providers as _providers
from app.ai import schemas as _s
from app.ai.models import AiBudgetPeriod, AiCall
from app.auth.config import get_auth_settings
from app.auth.service import effective_roles
from app.core.errors import AppError

Tenant = _uuid.UUID | None


def tenant_of(user: _t.Any) -> Tenant:
    if not _config.MULTI_TENANT:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise AppError("forbidden", "this needs a caller that belongs to a tenant", 403)
    return _t.cast(_uuid.UUID, tenant)


def _scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


def _now() -> datetime:
    return datetime.now(UTC)


def has_role(user: _t.Any, roles: tuple[str, ...]) -> bool:
    return not roles or bool(effective_roles(user.roles) & set(roles))


def require_call_role(user: _t.Any) -> None:
    """The gateway call gate: a caller needs one of call_roles or manage_roles (empty group = any signed-in user). Used by
    /ai/complete and by every feature that spends gateway budget on the caller's behalf (documents create, knowledge ask)."""
    groups = (_config.CALL_ROLES, _config.MANAGE_ROLES)
    if all(groups) and not any(has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)


def _fingerprint(*parts: object) -> str:
    """SALTED hash (HMAC-SHA256 keyed with the project's secret): a low-entropy prompt cannot be guessed from the ledger."""
    key = get_auth_settings().jwt_key.encode()
    return hmac.new(key, json.dumps(parts, separators=(",", ":"), sort_keys=True, default=str).encode(), hashlib.sha256).hexdigest()


def cost_micro_usd(model: str, input_tokens: int, output_tokens: int) -> int:
    """Integer micro-USD, rounded up per direction (never under-bills, never a float)."""
    price_in, price_out = _config.PRICES[model]
    return -(-(input_tokens * price_in) // 1_000_000) + -(-(output_tokens * price_out) // 1_000_000)


def period_start(now: datetime) -> date:
    day = now.astimezone(UTC).date()
    return day if _config.BUDGET_PERIOD == "day" else day.replace(day=1)



# --- budget rows ---------------------------------------------------------------------------------------------


async def _lock_period(session: AsyncSession, tenant: Tenant, start: date) -> AiBudgetPeriod:
    """Create the period row when missing, then lock it. All reservations and settlements of the period queue here."""
    values: dict[str, _t.Any] = {"id": _uuid.uuid4(), "period_start": start, "spent_micro_usd": 0, "reserved_micro_usd": 0}
    if tenant is not None:
        values["tenant_id"] = tenant
    await session.execute(_pg_insert(AiBudgetPeriod).values(**values).on_conflict_do_nothing())
    stmt = _scoped(_sa.select(AiBudgetPeriod).where(AiBudgetPeriod.period_start == start), AiBudgetPeriod, tenant)
    row = (await session.execute(stmt.with_for_update().execution_options(populate_existing=True))).scalar_one()
    return row


async def _release_stale(session: AsyncSession, tenant: Tenant, period: AiBudgetPeriod, now: datetime) -> None:
    cutoff = now - timedelta(seconds=_config.STALE_RESERVATION_SECONDS)
    stmt = _scoped(
        _sa.select(AiCall).where(
            AiCall.status == "reserved", AiCall.period_start == period.period_start, AiCall.created_at < cutoff
        ),
        AiCall,
        tenant,
    )
    for call in (await session.execute(stmt.with_for_update(skip_locked=True))).scalars():
        period.reserved_micro_usd = max(0, period.reserved_micro_usd - call.reserved_micro_usd)
        call.reserved_micro_usd = 0
        call.status = "error"
        call.error_code = "abandoned"
        call.finished_at = now


async def _release_stale_other_periods(
    session: AsyncSession, tenant: Tenant, caller: _t.Any, key: str, start: date, now: datetime
) -> None:
    """A crashed reservation of this key in an earlier period must not wedge the key (the unique index spans periods)."""
    cutoff = now - timedelta(seconds=_config.STALE_RESERVATION_SECONDS)
    stmt = _scoped(
        _sa.select(AiCall.period_start)
        .where(
            AiCall.caller_id == caller,
            AiCall.idempotency_key == key,
            AiCall.status == "reserved",
            AiCall.period_start != start,
            AiCall.created_at < cutoff,
        )
        .distinct(),
        AiCall,
        tenant,
    )
    for other in sorted((await session.execute(stmt)).scalars().all()):
        await _release_stale(session, tenant, await _lock_period(session, tenant, other), now)


def _parse_json(text: str | None) -> _t.Any | None:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict | list) else None


def _out(call: AiCall, text: str | None, replayed: bool) -> _s.CompleteOut:
    return _s.CompleteOut(
        call_id=call.id,
        stage=call.stage,
        provider=call.provider,
        model=call.model,
        status=_t.cast(_s.CallStatus, call.status),
        output_text=text,
        output_json=_parse_json(text),
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cost_micro_usd=call.cost_micro_usd,
        fallback_used=call.fallback_used,
        replayed=replayed,
        created_at=call.created_at,
    )


async def _replay(session: AsyncSession, tenant: Tenant, call_id: _uuid.UUID) -> _s.CompleteOut:
    """The result of the first call of an idempotency key; waits while that call is still in flight."""
    deadline = time.monotonic() + _config.WAIT_FOR_DUPLICATE_SECONDS
    while True:
        stmt = _scoped(_sa.select(AiCall).where(AiCall.id == call_id), AiCall, tenant)
        call = (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one()
        status, error_code = call.status, call.error_code
        out = _out(call, call.output_text, True) if status == "ok" else None
        await session.commit()
        if out is not None:
            return out
        if status == "error":
            raise AppError(error_code or "provider_error", "the first attempt of this call failed", 502)
        if time.monotonic() > deadline:
            raise AppError("call_in_progress", "the first call with this idempotency_key is still running", 409)
        await asyncio.sleep(50 / 1000)  # poll every 50 ms


async def _release_reservation(tenant: Tenant, start: date, call_id: _uuid.UUID, worst: int, code: str) -> None:
    """Release a reservation from an INDEPENDENT session (the request session may be cancelled or broken). A no-op when the
    call already left `reserved` (settled, or released as abandoned). Awaited under asyncio.shield by the caller."""
    from app.db import session_factory  # lazy: only on the failure path

    async with session_factory() as own:
        period = await _lock_period(own, tenant, start)
        row = (
            await own.execute(
                _sa.select(AiCall).where(AiCall.id == call_id).with_for_update().execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is not None and row.status == "reserved":
            period.reserved_micro_usd = max(0, period.reserved_micro_usd - worst)
            row.reserved_micro_usd = 0
            row.status, row.error_code, row.finished_at = "error", code, _now()
        await own.commit()


# --- the call ----------------------------------------------------------------------------------------------


async def complete(session: AsyncSession, user: _t.Any, body: _s.CompleteIn, *, retain: bool = True) -> _s.CompleteOut:
    """`retain=False` (documents, knowledge ask: their prompts hold permission-filtered text) stores only the hash and counts."""
    tenant = tenant_of(user)
    caller: _uuid.UUID | None = getattr(user, "id", None)  # plain value: a rollback expires the user object
    stage = _config.STAGES.get(body.stage)
    if stage is None:
        raise AppError("unknown_stage", f"there is no stage {body.stage!r}", 404)
    provider_name = str(stage["provider"])
    kind = str(_config.PROVIDERS[provider_name]["kind"])
    primary = str(stage["model"])
    fallback = stage["fallback_model"]
    stage_max = _t.cast(int, stage["max_output_tokens"])
    max_out = body.max_output_tokens if body.max_output_tokens is not None else stage_max
    if max_out > stage_max:
        raise AppError("validation_error", f"max_output_tokens is at most {stage_max} for this stage", 422)
    models = [primary] + ([str(fallback)] if fallback else [])
    contents = [m.content for m in body.messages]
    if sum(len(c) for c in contents) > _config.MAX_TOTAL_CHARS:
        raise AppError("validation_error", f"the messages are longer than {_config.MAX_TOTAL_CHARS} characters in total", 422)
    in_tokens = _providers.estimate_input_tokens(contents)
    worst = max(cost_micro_usd(m, in_tokens, max_out) for m in models)
    if worst > _config.PER_CALL_CAP_MICRO_USD:
        raise AppError(
            "per_call_cap_exceeded",
            "the worst-case cost of this call is above the per-call cap",
            422,
            [{"worst_case_micro_usd": worst, "per_call_cap_micro_usd": _config.PER_CALL_CAP_MICRO_USD}],
        )
    messages = [[m.role, m.content] for m in body.messages]
    keep_text = retain and not _config.ZERO_RETENTION
    prompt_hash = _fingerprint(body.stage, messages)
    request_hash = _fingerprint(prompt_hash, max_out, body.response_format)
    now = _now()
    start = period_start(now)

    # 1. reserve the worst case, all or nothing, with the period row locked
    period = await _lock_period(session, tenant, start)
    await _release_stale(session, tenant, period, now)  # before the replay lookup: a crashed first call must not wedge its key
    if body.idempotency_key is not None and caller is not None:
        await _release_stale_other_periods(session, tenant, caller, body.idempotency_key, start, now)
        found = (
            await session.execute(
                _scoped(
                    _sa.select(AiCall).where(
                        AiCall.caller_id == caller,
                        AiCall.idempotency_key == body.idempotency_key,
                        AiCall.status != "error",
                    ),
                    AiCall,
                    tenant,
                )
            )
        ).scalar_one_or_none()
        if found is not None:
            found_id, found_hash = found.id, found.request_hash
            await session.commit()
            if found_hash != request_hash:
                raise AppError("idempotency_conflict", "this idempotency_key was already used for a different call", 409)
            return await _replay(session, tenant, found_id)
    spent, reserved = period.spent_micro_usd, period.reserved_micro_usd
    if spent + reserved + worst > _config.BUDGET_LIMIT_MICRO_USD:
        await session.commit()  # keeps the stale releases; nothing else changed
        raise AppError(
            "budget_exceeded",
            "the AI budget of this period cannot cover this call",
            429,
            [
                {
                    "limit_micro_usd": _config.BUDGET_LIMIT_MICRO_USD,
                    "spent_micro_usd": spent,
                    "reserved_micro_usd": reserved,
                    "requested_micro_usd": worst,
                }
            ],
        )
    call_id = _uuid.uuid4()
    call = AiCall(
        id=call_id,
        caller_id=caller,
        stage=body.stage,
        provider=provider_name,
        model=primary,
        status="reserved",
        period_start=start,
        reserved_micro_usd=worst,
        prompt_hash=prompt_hash,
        prompt_text=json.dumps(messages, separators=(",", ":")) if keep_text else None,
        idempotency_key=body.idempotency_key,
        request_hash=request_hash,
        created_at=now,
    )
    if tenant is not None:
        call.tenant_id = tenant
    session.add(call)
    period.reserved_micro_usd = reserved + worst
    try:
        await session.commit()
    except IntegrityError:  # the same key won the race across a period boundary
        await session.rollback()
        again = (
            await session.execute(
                _scoped(
                    _sa.select(AiCall.id).where(
                        AiCall.caller_id == caller,
                        AiCall.idempotency_key == body.idempotency_key,
                        AiCall.status != "error",
                    ),
                    AiCall,
                    tenant,
                )
            )
        ).scalar_one_or_none()
        if again is None:
            raise
        return await _replay(session, tenant, again)

    try:
        # 2. the provider call, outside any lock; the primary model first, then the optional fallback
        used_model, fallback_used, result = primary, False, None
        for index, model in enumerate(models):
            try:
                result = await asyncio.wait_for(
                    _providers.complete(kind, model, contents, max_out, body.response_format == "json", index > 0, _config.FAKE_DIRECTIVES),
                    timeout=_config.PROVIDER_TIMEOUT_SECONDS,
                )
            except Exception:  # noqa: BLE001 - any provider failure releases the reservation
                continue
            used_model, fallback_used = model, index > 0
            break

        # 3. settle (or release) under the same lock
        period = await _lock_period(session, tenant, start)
        row = (
            await session.execute(
                _sa.select(AiCall).where(AiCall.id == call_id).with_for_update().execution_options(populate_existing=True)
            )
        ).scalar_one()
        if row.status != "reserved":  # released as abandoned while the provider was running
            await session.commit()
            raise AppError("call_expired", "the reservation of this call expired before the provider answered", 409)
        period.reserved_micro_usd = max(0, period.reserved_micro_usd - worst)
        row.reserved_micro_usd = 0
        row.finished_at = _now()
        if result is None:
            row.status, row.error_code = "error", "provider_error"
            await session.commit()
            raise AppError("provider_error", "the model provider failed; nothing was charged", 502)
        cost = min(cost_micro_usd(used_model, result.input_tokens, result.output_tokens), worst)  # never above the reservation
        row.model, row.fallback_used = used_model, fallback_used
        row.input_tokens, row.output_tokens, row.cost_micro_usd = result.input_tokens, result.output_tokens, cost
        period.spent_micro_usd += cost
        if body.response_format == "json" and _parse_json(result.text) is None:
            row.status, row.error_code = "error", "invalid_output"
            await session.commit()
            raise AppError("invalid_output", "the model did not return a JSON object", 502)
        row.status = "ok"
        row.output_text = result.text if keep_text else None
        out = _out(row, result.text, False)
        await session.commit()
        return out
    except AppError:  # every AppError of the settle step is raised after its own commit
        raise
    except BaseException:  # CancelledError (client disconnect), a DB error, a timeout: never leave the reservation held
        await asyncio.shield(_release_reservation(tenant, start, call_id, worst, "cancelled"))
        raise


# --- reads ---------------------------------------------------------------------------------------------------


def _call_out(row: AiCall) -> _s.CallOut:
    return _s.CallOut(
        id=row.id,
        caller_id=row.caller_id,
        stage=row.stage,
        provider=row.provider,
        model=row.model,
        status=_t.cast(_s.CallStatus, row.status),
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_micro_usd=row.cost_micro_usd,
        reserved_micro_usd=row.reserved_micro_usd,
        prompt_hash=row.prompt_hash,
        error_code=row.error_code,
        fallback_used=row.fallback_used,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def list_calls(
    session: AsyncSession,
    user: _t.Any,
    limit: int,
    offset: int,
    stage: str | None,
    status: str | None,
    caller_id: _uuid.UUID | None,
) -> tuple[list[_s.CallOut], int]:
    tenant = tenant_of(user)
    conditions: list[_t.Any] = []
    if stage is not None:
        conditions.append(AiCall.stage == stage)
    if status is not None:
        conditions.append(AiCall.status == status)
    if caller_id is not None:
        conditions.append(AiCall.caller_id == caller_id)
    total = await session.scalar(_scoped(_sa.select(_sa.func.count()).select_from(AiCall).where(*conditions), AiCall, tenant))
    rows = (
        await session.execute(
            _scoped(_sa.select(AiCall).where(*conditions), AiCall, tenant)
            .order_by(AiCall.created_at.desc(), AiCall.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return [_call_out(r) for r in rows], total or 0


async def usage(session: AsyncSession, user: _t.Any) -> _s.UsageOut:
    tenant = tenant_of(user)
    start = period_start(_now())
    period = (
        await session.execute(
            _scoped(_sa.select(AiBudgetPeriod).where(AiBudgetPeriod.period_start == start), AiBudgetPeriod, tenant)
        )
    ).scalar_one_or_none()
    spent = period.spent_micro_usd if period is not None else 0
    reserved = period.reserved_micro_usd if period is not None else 0
    counts: dict[str, int] = {"ok": 0, "error": 0}
    tokens_in = tokens_out = 0
    rows = await session.execute(
        _scoped(
            _sa.select(
                AiCall.status,
                _sa.func.count(),
                _sa.func.coalesce(_sa.func.sum(AiCall.input_tokens), 0),
                _sa.func.coalesce(_sa.func.sum(AiCall.output_tokens), 0),
            )
            .where(AiCall.period_start == start)
            .group_by(AiCall.status),
            AiCall,
            tenant,
        )
    )
    for status, n, t_in, t_out in rows:
        counts[status] = counts.get(status, 0) + int(n)
        tokens_in += int(t_in)
        tokens_out += int(t_out)
    await session.commit()
    return _s.UsageOut(
        period=_config.BUDGET_PERIOD,
        period_start=start,
        limit_micro_usd=_config.BUDGET_LIMIT_MICRO_USD,
        spent_micro_usd=spent,
        reserved_micro_usd=reserved,
        remaining_micro_usd=max(0, _config.BUDGET_LIMIT_MICRO_USD - spent - reserved),
        calls_ok=counts["ok"],
        calls_error=counts["error"],
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        zero_retention=_config.ZERO_RETENTION,
        region=_config.REGION,
    )
