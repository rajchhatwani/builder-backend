"""Prediction service (generated). A prediction is logged with its interval and model id; the actual outcome is
recorded later (once); the stats compare the two with integer arithmetic only (MAE x 1000 and interval coverage in
basis points, both rounded half to even)."""

import typing as _t
import uuid as _uuid
from datetime import UTC, datetime

import sqlalchemy as _sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operations.common import Tenant, scoped, tenant_of, tenant_values
from app.operations.prediction import adapter as _adapter
from app.operations.prediction import config as _config
from app.operations.prediction import schemas as _s
from app.operations.prediction.models import PredictionRecord

PREDICTOR: _adapter.Predictor = _adapter.FakePredictor(_config.MODEL_ID, _config.INTERVAL_BP)


def tenant(user: _t.Any) -> Tenant:
    return tenant_of(user, _config.MULTI_TENANT)


def record_out(row: PredictionRecord) -> _s.RecordOut:
    return _s.RecordOut(
        id=row.id, kind=row.kind, subject_ref=row.subject_ref, model_id=row.model_id, unit=row.unit, value=row.value,
        low=row.low, high=row.high, features=row.features, actual=row.actual, actual_at=row.actual_at,
        created_at=row.created_at,
    )


async def predict(session: AsyncSession, user: _t.Any, body: _s.PredictIn) -> _s.RecordOut:
    result = PREDICTOR.predict(body.kind, body.subject_ref, body.features)
    if not -_s.LIMIT <= result.low <= result.value <= result.high <= _s.LIMIT:
        raise AppError("invalid_features", "the features give a value outside the supported range", 422)
    row = PredictionRecord(
        kind=body.kind, subject_ref=body.subject_ref, model_id=result.model_id, unit=_config.UNIT, value=result.value,
        low=result.low, high=result.high, features=dict(body.features), created_by=getattr(user, "id", None),
        **tenant_values(tenant(user)),
    )
    session.add(row)
    await session.commit()
    return record_out(row)


async def _load(session: AsyncSession, tn: Tenant, record_id: _uuid.UUID) -> PredictionRecord:
    stmt = scoped(_sa.select(PredictionRecord).where(PredictionRecord.id == record_id), PredictionRecord, tn)
    row = (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "prediction not found", 404)
    return row


async def get_record(session: AsyncSession, user: _t.Any, record_id: _uuid.UUID) -> _s.RecordOut:
    return record_out(await _load(session, tenant(user), record_id))


async def record_actual(session: AsyncSession, user: _t.Any, record_id: _uuid.UUID, body: _s.ActualIn) -> _s.RecordOut:
    tn = tenant(user)
    await _load(session, tn, record_id)
    stmt = (
        _sa.update(PredictionRecord)
        .where(PredictionRecord.id == record_id, PredictionRecord.actual.is_(None))
        .values(actual=body.actual, actual_at=datetime.now(UTC))
    )
    result = await session.execute(scoped(stmt, PredictionRecord, tn))
    await session.commit()
    row = await _load(session, tn, record_id)
    if not result.rowcount and row.actual != body.actual:  # type: ignore[attr-defined]
        raise AppError("actual_already_recorded", "a different actual outcome is already recorded", 409)
    return record_out(row)


async def list_records(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, kind: str | None, subject_ref: str | None, has_actual: bool | None
) -> tuple[list[_s.RecordOut], int]:
    base = scoped(_sa.select(PredictionRecord), PredictionRecord, tenant(user))
    if kind is not None:
        base = base.where(PredictionRecord.kind == kind)
    if subject_ref is not None:
        base = base.where(PredictionRecord.subject_ref == subject_ref)
    if has_actual is not None:
        base = base.where(PredictionRecord.actual.is_not(None) if has_actual else PredictionRecord.actual.is_(None))
    total = (await session.execute(_sa.select(_sa.func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(PredictionRecord.created_at.desc(), PredictionRecord.id).limit(limit).offset(offset))).scalars()
    return [record_out(r) for r in rows], int(total)


async def stats(session: AsyncSession, user: _t.Any, kind: str | None, model_id: str | None) -> _s.StatsOut:
    R = PredictionRecord
    has = R.actual.is_not(None)
    stmt = scoped(
        _sa.select(
            _sa.func.count(),
            _sa.func.count(R.actual),
            _sa.func.coalesce(_sa.func.sum(_sa.case((has, _sa.func.abs(R.actual - R.value)), else_=0)), 0),
            _sa.func.coalesce(_sa.func.sum(_sa.case((_sa.and_(has, R.actual >= R.low, R.actual <= R.high), 1), else_=0)), 0),
        ),
        R, tenant(user),
    )
    if kind is not None:
        stmt = stmt.where(R.kind == kind)
    if model_id is not None:
        stmt = stmt.where(R.model_id == model_id)
    logged, with_actual, abs_sum, covered = (await session.execute(stmt)).one()
    abs_sum, covered = int(abs_sum), int(covered)
    return _s.StatsOut(
        logged=int(logged), with_actual=int(with_actual), abs_error_sum=abs_sum, covered=covered,
        mae_milli=_adapter.divide_half_even(abs_sum * 1000, with_actual) if with_actual else None,
        coverage_bp=_adapter.error_rate_bp(covered, with_actual) if with_actual else None,
    )
