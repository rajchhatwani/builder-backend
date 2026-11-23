"""Booking service (generated). The rules, in one place.

* Resources (a practitioner, a room, a pool of units) belong to a spec KIND with a mode. `slot`: one fixed-length
  slot of the resource's weekly schedule (timezone aware, stored UTC); `range`: any time range; `pool`: a quantity
  of `capacity` units over a time range. Pure rules: app/booking/rules.py.
* Double booking is refused by the database: an EXCLUDE constraint over (tenant, resource, time range) for active
  slot / range bookings (-> 409 slot_taken). Pool capacity is checked inside the booking transaction while the
  resource row is locked (FOR UPDATE), so parallel requests queue and capacity is never exceeded
  (-> 409 capacity_exceeded).
* A booking starts as a hold (TTL from the spec). held -> confirmed | expired | cancelled; confirmed -> cancelled.
  A stale hold is turned into `expired` before every create, list, get and availability read (lazy), and by
  `sweep_expired` (POST /booking/expire). Expired holds therefore never block a slot.
* Create is idempotent per (caller, idempotency_key): the same key and body returns the first booking.
* Cancellation fee: rules.cancellation_fee (free until N hours before the start, else a flat integer fee_minor).
"""

import hashlib
import json
import typing as _t
import uuid as _uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as _sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import effective_roles
from app.booking import config as _config
from app.booking import rules as _rules
from app.booking import schemas as _s
from app.booking.models import Booking, BookingResource
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


def _has_listed_role(user: _t.Any, roles: tuple[str, ...]) -> bool:
    return bool(roles) and bool(effective_roles(user.roles) & set(roles))


def is_manager(user: _t.Any) -> bool:
    return _has_listed_role(user, _config.MANAGE_ROLES)  # an empty manage_roles makes nobody a manager


def sees_all(user: _t.Any) -> bool:
    """Managers see every booking; others only their own when OWN_ONLY (or when they cannot read at large)."""
    if is_manager(user):
        return True
    return not _config.OWN_ONLY and has_role(user, _config.READ_ROLES)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AppError("invalid_time", "times need a timezone offset, e.g. 2026-12-01T09:00:00+01:00", 422)
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise AppError("invalid_time", "that time is out of range", 422) from exc


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"), sort_keys=True, default=str).encode()).hexdigest()


# --- resources ---------------------------------------------------------------------------------


def _resource_out(row: BookingResource) -> _s.ResourceOut:
    return _s.ResourceOut(
        id=row.id,
        kind=row.kind,
        mode=_t.cast(_s.Mode, row.mode),
        name=row.name,
        timezone=row.timezone,
        slot_minutes=row.slot_minutes,
        schedule=row.schedule,
        capacity=row.capacity,
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        active=row.active,
        created_at=row.created_at,
    )


async def _resource(session: AsyncSession, tenant: Tenant, resource_id: _uuid.UUID, lock: bool = False) -> BookingResource:
    stmt = _scoped(_sa.select(BookingResource).where(BookingResource.id == resource_id), BookingResource, tenant)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "resource not found", 404)
    return row


def _check_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise AppError("invalid_timezone", "not an IANA timezone", 422) from exc


def _schedule_json(schedule: dict[str, list[_s.Window]]) -> dict[str, list[dict[str, str]]]:
    return {day: [{"start": w.start, "end": w.end} for w in windows] for day, windows in schedule.items()}


def _check_schedule(schedule: _t.Any, slot_minutes: int) -> None:
    problem = _rules.validate_schedule(schedule, slot_minutes)
    if problem is not None:
        raise AppError("invalid_schedule", problem, 422)


async def create_resource(session: AsyncSession, user: _t.Any, body: _s.ResourceCreate) -> _s.ResourceOut:
    tenant = tenant_of(user)
    kind = _config.KINDS.get(body.kind)
    if kind is None:
        raise AppError("unknown_kind", f"kind must be one of {', '.join(sorted(_config.KINDS))}", 422)
    mode = str(kind["mode"])
    timezone_name = body.timezone or str(kind["timezone"])
    _check_timezone(timezone_name)
    schedule: _t.Any = None
    slot_minutes: int | None = None
    capacity = 1
    min_minutes: int | None = None
    max_minutes: int | None = None
    if mode == "slot":
        slot_minutes = int(_t.cast(int, kind["slot_minutes"]))
        schedule = _schedule_json(body.schedule) if body.schedule is not None else kind["schedule"]
        _check_schedule(schedule, slot_minutes)
        if body.capacity not in (None, 1):
            raise AppError("invalid_capacity", "a slot resource holds one booking at a time", 422)
    else:
        if body.schedule is not None:
            raise AppError("invalid_schedule", "only a slot resource has a weekly schedule", 422)
        min_minutes = int(_t.cast(int, kind["min_minutes"]))
        max_minutes = int(_t.cast(int, kind["max_minutes"]))
        if mode == "pool":
            capacity = body.capacity if body.capacity is not None else int(_t.cast(int, kind["capacity"]))
        elif body.capacity not in (None, 1):
            raise AppError("invalid_capacity", "a range resource holds one booking at a time", 422)
    row_id = _uuid.uuid4()
    values: dict[str, _t.Any] = {
        "id": row_id,
        "kind": body.kind,
        "mode": mode,
        "name": body.name,
        "timezone": timezone_name,
        "slot_minutes": slot_minutes,
        "schedule": schedule,
        "capacity": capacity,
        "min_minutes": min_minutes,
        "max_minutes": max_minutes,
        "active": body.active,
    }
    if tenant is not None:
        values["tenant_id"] = tenant
    await session.execute(_sa.insert(BookingResource).values(**values))
    await session.commit()
    return _resource_out(await _resource(session, tenant, row_id))


async def list_resources(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, kind: str | None, active: bool | None
) -> tuple[list[_s.ResourceOut], int]:
    tenant = tenant_of(user)
    base = _scoped(_sa.select(BookingResource), BookingResource, tenant)
    if kind is not None:
        base = base.where(BookingResource.kind == kind)
    if active is not None:
        base = base.where(BookingResource.active == active)
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(base.order_by(BookingResource.name, BookingResource.id).limit(limit).offset(offset))
    return [_resource_out(r) for r in rows.scalars().all()], int(total)


async def get_resource(session: AsyncSession, user: _t.Any, resource_id: _uuid.UUID) -> _s.ResourceOut:
    return _resource_out(await _resource(session, tenant_of(user), resource_id))


async def update_resource(
    session: AsyncSession, user: _t.Any, resource_id: _uuid.UUID, body: _s.ResourceUpdate
) -> _s.ResourceOut:
    tenant = tenant_of(user)
    row = await _resource(session, tenant, resource_id, lock=True)
    values: dict[str, _t.Any] = {}
    if body.name is not None:
        values["name"] = body.name
    if body.active is not None:
        values["active"] = body.active
    if body.timezone is not None:
        _check_timezone(body.timezone)
        values["timezone"] = body.timezone
    if body.schedule is not None:
        if row.mode != "slot":
            raise AppError("invalid_schedule", "only a slot resource has a weekly schedule", 422)
        values["schedule"] = _schedule_json(body.schedule)
        _check_schedule(values["schedule"], int(row.slot_minutes or 0))
    if values:
        await session.execute(_sa.update(BookingResource).where(BookingResource.id == resource_id).values(**values))
    await session.commit()
    return _resource_out(await _resource(session, tenant, resource_id))


# --- holds: lazy expiry and the sweep ---------------------------------------------------------


async def sweep_expired(session: AsyncSession, tenant: Tenant, resource_id: _uuid.UUID | None = None) -> int:
    """Turn every hold past its TTL into `expired` (stale rows are locked with SKIP LOCKED, in id order, so two
    sweeps never wait for each other). Does not commit: the caller does."""
    now = _now()
    stale = _sa.select(Booking.id).where(Booking.status == "held", Booking.hold_expires_at <= now)
    stale = _scoped(stale, Booking, tenant)
    if resource_id is not None:
        stale = stale.where(Booking.resource_id == resource_id)
    stale = stale.order_by(Booking.id).with_for_update(skip_locked=True)
    stmt = (
        _sa.update(Booking)
        .where(Booking.id.in_(stale.scalar_subquery()))
        .values(status="expired", expired_at=now, hold_expires_at=None)
        .returning(Booking.id)
    )
    return len((await session.execute(stmt)).all())


async def expire_holds(session: AsyncSession, user: _t.Any) -> _s.ExpireOut:
    count = await sweep_expired(session, tenant_of(user))
    await session.commit()
    return _s.ExpireOut(expired=count)


async def _lazy_expire(session: AsyncSession, tenant: Tenant, resource_id: _uuid.UUID | None = None) -> None:
    await sweep_expired(session, tenant, resource_id)
    await session.commit()


# --- bookings: output and visibility -----------------------------------------------------------


def _stale_hold(row: Booking) -> bool:
    return row.status == "held" and row.hold_expires_at is not None and row.hold_expires_at <= _now()


def _out(row: Booking, res: BookingResource) -> _s.BookingOut:
    stale = _stale_hold(row)  # a hold past its TTL reads as expired before any sweep has run
    return _s.BookingOut(
        id=row.id,
        resource_id=row.resource_id,
        resource_name=res.name,
        kind=res.kind,
        mode=_t.cast(_s.Mode, res.mode),
        status=_t.cast(_s.Status, "expired" if stale else row.status),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        quantity=row.quantity,
        hold_expires_at=row.hold_expires_at if row.status == "held" and not stale else None,
        customer_id=row.customer_id,
        customer_ref=row.customer_ref,
        notes=row.notes,
        idempotency_key=row.idempotency_key,
        cancel_fee_minor=row.cancel_fee_minor,
        fee_currency=row.fee_currency,
        cancelled_at=row.cancelled_at,
        confirmed_at=row.confirmed_at,
        expired_at=row.hold_expires_at if stale else row.expired_at,
        created_at=row.created_at,
    )


async def _booking(
    session: AsyncSession, tenant: Tenant, booking_id: _uuid.UUID, user: _t.Any | None = None, lock: bool = False
) -> Booking:
    """The booking, or 404. `user` given: a booking the caller may not see is also 404."""
    stmt = _scoped(_sa.select(Booking).where(Booking.id == booking_id), Booking, tenant)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None or (user is not None and not sees_all(user) and row.customer_id != getattr(user, "id", None)):
        raise AppError("not_found", "booking not found", 404)
    return row


async def _booking_out(session: AsyncSession, tenant: Tenant, row: Booking) -> _s.BookingOut:
    return _out(row, await _resource(session, tenant, row.resource_id))


async def get_booking(session: AsyncSession, user: _t.Any, booking_id: _uuid.UUID) -> _s.BookingOut:
    tenant = tenant_of(user)
    return await _booking_out(session, tenant, await _booking(session, tenant, booking_id, user))


async def list_bookings(
    session: AsyncSession,
    user: _t.Any,
    limit: int,
    offset: int,
    resource_id: _uuid.UUID | None,
    status: str | None,
    window_from: datetime | None,
    window_to: datetime | None,
) -> tuple[list[_s.BookingOut], int]:
    tenant = tenant_of(user)  # reads never sweep or commit: a stale hold is reported as expired by _out / the status filter
    base = _scoped(_sa.select(Booking), Booking, tenant)
    if not sees_all(user):
        base = base.where(Booking.customer_id == getattr(user, "id", None))
    if resource_id is not None:
        base = base.where(Booking.resource_id == resource_id)
    if status is not None:
        live = _sa.and_(Booking.status == "held", Booking.hold_expires_at > _now())
        gone = _sa.and_(Booking.status == "held", Booking.hold_expires_at <= _now())
        if status == "held":
            base = base.where(live)
        elif status == "expired":
            base = base.where(_sa.or_(Booking.status == "expired", gone))
        else:
            base = base.where(Booking.status == status)
    if window_from is not None:
        base = base.where(Booking.ends_at > _utc(window_from))
    if window_to is not None:
        base = base.where(Booking.starts_at < _utc(window_to))
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(Booking.starts_at, Booking.id).limit(limit).offset(offset))).scalars().all()
    resources: dict[_uuid.UUID, BookingResource] = {}
    for rid in {r.resource_id for r in rows}:
        resources[rid] = await _resource(session, tenant, rid)
    return [_out(r, resources[r.resource_id]) for r in rows], int(total)


# --- availability ------------------------------------------------------------------------------


async def _active_intervals(
    session: AsyncSession, tenant: Tenant, resource_id: _uuid.UUID, start: datetime, end: datetime
) -> list[tuple[datetime, datetime, int]]:
    now = _now()
    stmt = _scoped(
        _sa.select(Booking.starts_at, Booking.ends_at, Booking.quantity).where(
            Booking.resource_id == resource_id,
            Booking.starts_at < end,
            Booking.ends_at > start,
            _sa.or_(Booking.status == "confirmed", _sa.and_(Booking.status == "held", Booking.hold_expires_at > now)),
        ),
        Booking,
        tenant,
    )
    return [(a, b, q) for a, b, q in (await session.execute(stmt)).all()]


async def availability(
    session: AsyncSession, user: _t.Any, resource_id: _uuid.UUID, first: date, last: date, include_taken: bool
) -> _s.AvailabilityOut:
    tenant = tenant_of(user)
    res = await _resource(session, tenant, resource_id)
    if res.mode != "slot" or res.slot_minutes is None or res.schedule is None:
        raise AppError("not_slot_resource", "only a slot resource has an availability list (see /capacity)", 422)
    if last < first or (last - first).days + 1 > _config.MAX_AVAILABILITY_DAYS:
        raise AppError("invalid_range", f"`to` is not before `from` and at most {_config.MAX_AVAILABILITY_DAYS} days", 422)
    now = _now()
    horizon = now + timedelta(days=_config.MAX_HORIZON_DAYS)
    # nothing is bookable before today or beyond the horizon: clamp the walk (also keeps date maths in range)
    first = max(first, now.date() - timedelta(days=1))
    last = min(last, horizon.date() + timedelta(days=1))
    slots = [
        (s, e)
        for s, e in (_rules.slots_between(res.schedule, res.timezone, res.slot_minutes, first, last) if first <= last else [])
        if s > now and s <= horizon
    ]
    busy: list[tuple[datetime, datetime]] = []
    if slots and res.active:
        busy = [(a, b) for a, b, _ in await _active_intervals(session, tenant, res.id, slots[0][0], slots[-1][1])]
    marked = _rules.free_slots(slots, busy) if res.active else [(s, e, False) for s, e in slots]
    return _s.AvailabilityOut(
        resource_id=res.id,
        timezone=res.timezone,
        slot_minutes=res.slot_minutes,
        slots=[_s.SlotOut(starts_at=s, ends_at=e, free=free) for s, e, free in marked if free or include_taken],
    )


async def capacity(
    session: AsyncSession, user: _t.Any, resource_id: _uuid.UUID, starts_at: datetime, ends_at: datetime
) -> _s.CapacityOut:
    tenant = tenant_of(user)
    start, end = _utc(starts_at), _utc(ends_at)
    res = await _resource(session, tenant, resource_id)
    if res.mode == "slot":
        raise AppError("not_pool_resource", "a slot resource has an availability list instead", 422)
    if end <= start:
        raise AppError("invalid_range", "ends_at must be after starts_at", 422)
    if end - start > timedelta(days=_config.MAX_AVAILABILITY_DAYS):
        raise AppError("invalid_range", f"the range is at most {_config.MAX_AVAILABILITY_DAYS} days", 422)
    booked = _rules.booked_units(await _active_intervals(session, tenant, res.id, start, end), start, end)
    return _s.CapacityOut(resource_id=res.id, capacity=res.capacity, booked=booked, free=max(res.capacity - booked, 0))


# --- create ------------------------------------------------------------------------------------


async def _by_key(session: AsyncSession, tenant: Tenant, user_id: _uuid.UUID | None, key: str) -> Booking | None:
    stmt = _scoped(
        _sa.select(Booking).where(Booking.idempotency_key == key, Booking.customer_id == user_id),
        Booking,
        tenant,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _is_overlap(exc: IntegrityError) -> bool:
    text = str(exc.orig)
    return "ex_bookings_no_overlap" in text or getattr(exc.orig, "sqlstate", None) == "23P01"


async def create_booking(session: AsyncSession, user: _t.Any, body: _s.BookingCreate) -> tuple[_s.BookingOut, bool]:
    tenant = tenant_of(user)
    user_id: _uuid.UUID | None = getattr(user, "id", None)  # plain value: a rollback expires the user object
    start = _utc(body.starts_at)
    end_in = _utc(body.ends_at) if body.ends_at is not None else None
    await _lazy_expire(session, tenant, body.resource_id)
    res = await _resource(session, tenant, body.resource_id)
    # plain values: a rollback below expires the loaded rows
    mode, rid, slot_minutes, schedule, tz_name, capacity_units = res.mode, res.id, res.slot_minutes, res.schedule, res.timezone, res.capacity
    min_minutes, max_minutes, active = res.min_minutes, res.max_minutes, res.active
    fingerprint = _fingerprint(
        str(rid), start.isoformat(), end_in.isoformat() if end_in else None, body.quantity, body.confirm, body.customer_ref, body.notes
    )

    async def replay() -> Booking | None:
        if body.idempotency_key is None:
            return None
        existing = await _by_key(session, tenant, user_id, body.idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != fingerprint:
            raise AppError("idempotency_conflict", "this idempotency_key was already used for a different booking", 409)
        if existing.status in ("expired", "cancelled"):
            raise AppError(
                "idempotency_key_spent",
                f"that idempotency_key belongs to a booking that is now {existing.status}: use a new idempotency_key to book again",
                409,
            )
        return existing

    found = await replay()
    if found is not None:
        return await _booking_out(session, tenant, found), True
    if not active:
        raise AppError("resource_inactive", "this resource is not bookable right now", 422)
    now = _now()
    if start <= now or start > now + timedelta(days=_config.MAX_HORIZON_DAYS):
        raise AppError("outside_availability", "the start is in the past or beyond the booking horizon", 422)
    if mode == "slot":
        assert slot_minutes is not None and schedule is not None
        end = start + timedelta(minutes=slot_minutes)
        if end_in is not None and end_in != end:
            raise AppError("invalid_range", f"a slot is {slot_minutes} minutes: leave ends_at out or use start + slot", 422)
        if body.quantity != 1:
            raise AppError("invalid_quantity", "a slot booking is for one", 422)
        if not _rules.is_slot_start(schedule, tz_name, slot_minutes, start):
            raise AppError("outside_availability", "this is not a slot of the resource's schedule", 422)
    else:
        if end_in is None or end_in <= start:
            raise AppError("invalid_range", "ends_at is required and after starts_at", 422)
        end = end_in
        minutes = (end - start).total_seconds() / 60
        if not (_t.cast(int, min_minutes) <= minutes <= _t.cast(int, max_minutes)):
            raise AppError("invalid_range", f"the duration is {min_minutes}..{max_minutes} minutes", 422, [{"min_minutes": min_minutes, "max_minutes": max_minutes}])
        if mode == "range" and body.quantity != 1:
            raise AppError("invalid_quantity", "a range booking is for one", 422)
    if mode == "pool":
        if body.quantity > capacity_units:
            raise AppError("capacity_exceeded", "more than the pool holds", 409, [{"capacity": capacity_units, "requested": body.quantity}])
        await _resource(session, tenant, rid, lock=True)  # queue pool bookings of this resource
        found = await replay()  # a parallel request with the same key finished while we waited
        if found is not None:
            found_id = found.id
            await session.rollback()  # releases the resource lock; the rollback expires loaded rows, so reload
            return await _booking_out(session, tenant, await _booking(session, tenant, found_id)), True
        await sweep_expired(session, tenant, rid)
        booked = _rules.booked_units(await _active_intervals(session, tenant, rid, start, end), start, end)
        if booked + body.quantity > capacity_units:
            await session.rollback()
            raise AppError(
                "capacity_exceeded",
                "the pool has no room for that quantity in that period",
                409,
                [{"capacity": capacity_units, "booked": booked, "requested": body.quantity}],
            )
    if not body.confirm and user_id is not None:
        held = await session.scalar(
            _scoped(
                _sa.select(_sa.func.count()).select_from(Booking).where(
                    Booking.customer_id == user_id, Booking.status == "held", Booking.hold_expires_at > now
                ),
                Booking,
                tenant,
            )
        )
        if (held or 0) >= _config.MAX_ACTIVE_HOLDS:
            await session.rollback()
            raise AppError("too_many_holds", f"at most {_config.MAX_ACTIVE_HOLDS} open holds per person: confirm or cancel one", 429)
    booking_id = _uuid.uuid4()
    values: dict[str, _t.Any] = {
        "id": booking_id,
        "resource_id": rid,
        "status": "confirmed" if body.confirm else "held",
        "exclusive": mode != "pool",
        "starts_at": start,
        "ends_at": end,
        "quantity": body.quantity,
        "hold_expires_at": None if body.confirm else min(_rules.hold_deadline(now, _config.HOLD_TTL_SECONDS), start),
        "customer_id": user_id,
        "customer_ref": body.customer_ref,
        "notes": body.notes,
        "idempotency_key": body.idempotency_key,
        "request_hash": fingerprint,
        "confirmed_at": now if body.confirm else None,
    }
    if tenant is not None:
        values["tenant_id"] = tenant
    try:
        await session.execute(_sa.insert(Booking).values(**values))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # a parallel request with the same key may have won (either index can report first): replay it
        found = await replay()
        if found is not None:
            return await _booking_out(session, tenant, found), True
        if _is_overlap(exc):
            raise AppError("slot_taken", "that time is already booked", 409) from exc
        raise
    return await _booking_out(session, tenant, await _booking(session, tenant, booking_id)), False


# --- confirm / cancel --------------------------------------------------------------------------


def _may_act(user: _t.Any, row: Booking) -> None:
    if not is_manager(user) and row.customer_id != getattr(user, "id", None):
        raise AppError("forbidden", "you can only change your own bookings", 403)


async def confirm_booking(session: AsyncSession, user: _t.Any, booking_id: _uuid.UUID) -> _s.BookingOut:
    tenant = tenant_of(user)
    row = await _booking(session, tenant, booking_id, user, lock=True)
    _may_act(user, row)
    status_was, hold_until = row.status, row.hold_expires_at
    if status_was == "confirmed":  # a retried confirm (lost response) is idempotent: 200 with the booking
        done = await _booking_out(session, tenant, row)
        await session.rollback()
        return done
    if status_was == "held" and _rules.hold_expired(hold_until, _now()):
        await session.execute(
            _sa.update(Booking).where(Booking.id == booking_id).values(status="expired", expired_at=_now(), hold_expires_at=None)
        )
        await session.commit()
        raise AppError("hold_expired", "the hold ran out: book again", 410)
    if status_was == "expired":
        await session.rollback()
        raise AppError("hold_expired", "the hold ran out: book again", 410)
    if _rules.hold_expired(row.starts_at, _now()):
        await session.rollback()
        raise AppError("invalid_transition", "that booking has already started", 409)
    if not _rules.can_transition(status_was, "confirmed"):
        await session.rollback()
        raise AppError("invalid_transition", f"a {status_was} booking cannot be confirmed", 409)
    await session.execute(
        _sa.update(Booking).where(Booking.id == booking_id).values(status="confirmed", confirmed_at=_now(), hold_expires_at=None)
    )
    await session.commit()
    return await _booking_out(session, tenant, await _booking(session, tenant, booking_id))


async def cancel_booking(
    session: AsyncSession, user: _t.Any, booking_id: _uuid.UUID, body: _s.CancelIn
) -> _s.BookingOut:
    tenant = tenant_of(user)
    row = await _booking(session, tenant, booking_id, user, lock=True)
    _may_act(user, row)
    status_was, starts_at, hold_until = row.status, row.starts_at, row.hold_expires_at
    by_manager_for_other = is_manager(user) and row.customer_id != getattr(user, "id", None)
    now = _now()
    if status_was == "held" and _rules.hold_expired(hold_until, now):
        await session.execute(
            _sa.update(Booking).where(Booking.id == booking_id).values(status="expired", expired_at=now, hold_expires_at=None)
        )
        await session.commit()
        raise AppError("invalid_transition", "an expired booking cannot be cancelled", 409)
    if not _rules.can_transition(status_was, "cancelled"):
        await session.rollback()
        raise AppError("invalid_transition", f"a {status_was} booking cannot be cancelled", 409)
    if not _rules.can_cancel_now(status_was, starts_at, now):
        await session.rollback()
        raise AppError("invalid_transition", "that booking has already started", 409)
    # a manager cancelling someone else's booking (the clinic's decision) never charges the customer
    fee = 0 if by_manager_for_other else _rules.cancellation_fee(status_was, starts_at, now, _config.FREE_CANCEL_HOURS, _config.CANCEL_FEE_MINOR)
    await session.execute(
        _sa.update(Booking)
        .where(Booking.id == booking_id)
        .values(
            status="cancelled",
            cancelled_at=now,
            cancel_fee_minor=fee,
            fee_currency=_config.FEE_CURRENCY,
            cancel_reason=body.reason,
            hold_expires_at=None,
        )
    )
    await session.commit()
    return await _booking_out(session, tenant, await _booking(session, tenant, booking_id))
