"""Location service (generated). One row per subject holds the latest position; a report applies only when its `seq`
is newer than the stored one (atomic in the database: `ON CONFLICT DO UPDATE ... WHERE seq < new seq`), so retries and
out-of-order delivery are safe. History is bounded to HISTORY_CAP rows per subject (oldest deleted)."""

import typing as _t
from datetime import UTC, datetime, timedelta

import sqlalchemy as _sa
from sqlalchemy.dialects import postgresql as _pg
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operations.common import Tenant, scoped, tenant_of, tenant_values
from app.operations.geo import service as _geo
from app.operations.location import config as _config
from app.operations.location import schemas as _s
from app.operations.location.models import LocationHistory, LocationPosition
from app.operations.points import coords


def tenant(user: _t.Any) -> Tenant:
    return tenant_of(user, _config.MULTI_TENANT)


def position_out(row: LocationPosition) -> _s.PositionOut:
    return _s.PositionOut(
        subject_id=row.subject_id, subject_kind=row.subject_kind, seq=row.seq, recorded_at=row.recorded_at,
        updated_at=row.updated_at, **coords(row.lat_micro, row.lng_micro),
    )


async def _current(session: AsyncSession, tn: Tenant, subject_id: str) -> LocationPosition | None:
    stmt = scoped(_sa.select(LocationPosition).where(LocationPosition.subject_id == subject_id), LocationPosition, tn)
    return (await session.execute(stmt)).scalar_one_or_none()


async def report(session: AsyncSession, user: _t.Any, body: _s.PositionIn) -> tuple[_s.PositionResult, bool]:
    """(result, applied)."""
    tn = tenant(user)
    lat, lng = body.micro
    now = datetime.now(UTC)
    recorded = body.recorded_at or now
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=UTC)
    if recorded > now + timedelta(seconds=_config.MAX_FUTURE_SECONDS):
        raise AppError("future_timestamp", "recorded_at is more than 5 minutes in the future", 422)
    existing = await _current(session, tn, body.subject_id)
    if existing is None:
        # serialise new-subject creation per tenant so the count below cannot be raced past MAX_SUBJECTS
        await session.execute(_sa.select(_sa.func.pg_advisory_xact_lock(_sa.func.hashtext(f"location_subjects:{tn}"))))
        existing = await _current(session, tn, body.subject_id)
    if existing is None:
        total = (await session.execute(scoped(_sa.select(_sa.func.count()).select_from(LocationPosition), LocationPosition, tn))).scalar_one()
        if total >= _config.MAX_SUBJECTS:
            raise AppError("limit_reached", f"at most {_config.MAX_SUBJECTS} subjects", 422)
    values: dict[str, _t.Any] = {
        "subject_id": body.subject_id, "subject_kind": body.subject_kind, "lat_micro": lat, "lng_micro": lng,
        "seq": body.seq, "recorded_at": recorded, "updated_at": now, **tenant_values(tn),
    }
    insert = _pg.insert(LocationPosition).values(**values)
    stmt = insert.on_conflict_do_update(
        constraint="uq_location_positions_subject",
        set_={
            "subject_kind": _sa.func.coalesce(insert.excluded.subject_kind, LocationPosition.subject_kind),
            "lat_micro": insert.excluded.lat_micro, "lng_micro": insert.excluded.lng_micro,
            "seq": insert.excluded.seq, "recorded_at": insert.excluded.recorded_at, "updated_at": insert.excluded.updated_at,
        },
        where=LocationPosition.seq < insert.excluded.seq,
    ).returning(LocationPosition)
    row = (await session.execute(stmt, execution_options={"populate_existing": True})).scalar_one_or_none()
    if row is None:  # an equal or newer seq is stored: ignore this report
        await session.rollback()
        current = await _current(session, tn, body.subject_id)
        assert current is not None
        return _s.PositionResult(applied=False, reason="stale", position=position_out(current)), False
    await session.execute(
        _pg.insert(LocationHistory)
        .values(subject_id=body.subject_id, seq=body.seq, lat_micro=lat, lng_micro=lng, recorded_at=recorded, **tenant_values(tn))
        .on_conflict_do_nothing(constraint="uq_location_history_subject_seq")
    )
    keep = scoped(_sa.select(LocationHistory.seq).where(LocationHistory.subject_id == body.subject_id), LocationHistory, tn)
    await session.execute(
        scoped(_sa.delete(LocationHistory).where(LocationHistory.subject_id == body.subject_id), LocationHistory, tn).where(
            LocationHistory.seq.in_(keep.order_by(LocationHistory.seq.desc()).offset(_config.HISTORY_CAP))
        )
    )
    events: list[_s.FenceEvent] = []
    _inside, found = await _geo.evaluate_point(session, tn, body.subject_id, lat, lng)
    events = [_s.FenceEvent(**_geo.event_out(e).model_dump()) for e in found]
    out = _s.PositionResult(applied=True, position=position_out(row), geofence_events=events)
    await session.commit()
    return out, True


async def latest(session: AsyncSession, user: _t.Any, subject_id: str) -> _s.PositionOut:
    row = await _current(session, tenant(user), subject_id)
    if row is None:
        raise AppError("not_found", "no position for this subject", 404)
    return position_out(row)


async def history(session: AsyncSession, user: _t.Any, subject_id: str, limit: int) -> _s.HistoryOut:
    tn = tenant(user)
    if await _current(session, tn, subject_id) is None:
        raise AppError("not_found", "no position for this subject", 404)
    stmt = scoped(_sa.select(LocationHistory).where(LocationHistory.subject_id == subject_id), LocationHistory, tn)
    rows = (await session.execute(stmt.order_by(LocationHistory.seq.desc()).limit(limit))).scalars()
    items = [
        _s.HistoryRow(subject_id=r.subject_id, seq=r.seq, recorded_at=r.recorded_at, **coords(r.lat_micro, r.lng_micro))
        for r in rows
    ]
    return _s.HistoryOut(items=items, retention_cap=_config.HISTORY_CAP)


async def in_box(
    session: AsyncSession, user: _t.Any, min_lat: int, min_lng: int, max_lat: int, max_lng: int, kind: str | None, limit: int
) -> _s.BoxOut:
    for value, low, high in ((min_lat, -90_000_000, 90_000_000), (max_lat, -90_000_000, 90_000_000), (min_lng, -180_000_000, 180_000_000), (max_lng, -180_000_000, 180_000_000)):
        if not low <= value <= high:
            raise AppError("invalid_box", "box coordinates are out of range", 422)
    if min_lat > max_lat:
        raise AppError("invalid_box", "min_lat_micro must not exceed max_lat_micro", 422)
    stmt = scoped(_sa.select(LocationPosition), LocationPosition, tenant(user)).where(
        LocationPosition.lat_micro.between(min_lat, max_lat)
    )
    if min_lng <= max_lng:
        stmt = stmt.where(LocationPosition.lng_micro.between(min_lng, max_lng))
    else:  # crosses the antimeridian
        stmt = stmt.where(_sa.or_(LocationPosition.lng_micro >= min_lng, LocationPosition.lng_micro <= max_lng))
    if kind is not None:
        stmt = stmt.where(LocationPosition.subject_kind == kind)
    rows = list((await session.execute(stmt.order_by(LocationPosition.subject_id).limit(limit + 1))).scalars())
    return _s.BoxOut(items=[position_out(r) for r in rows[:limit]], truncated=len(rows) > limit)
