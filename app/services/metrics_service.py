"""Metrics layer + scheduled reports (B4-4, C22).

One definition (table `metrics`, versioned) serves the live API value and every report that lists
its key; reports never copy a definition. A report run stores {metric_key: {value, version}}.

Scheduling: `fire_due_reports(session, now)` is idempotent per slot. The unique
(report_id, scheduled_for) index plus ON CONFLICT DO NOTHING makes N concurrent schedulers store
each slot exactly once. Catch-up policy: after downtime only the LATEST missed slot fires (never a
backlog). A report starts counting from the moment it is created or (re)enabled or its schedule
changes: `last_scheduled_for` is set to that time, so an old slot never fires retroactively.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs_cron
from app.core import metrics as mx
from app.core.spec_models import SpecEntity
from app.exceptions import AppError
from app.models.data_import import ImportedRecord
from app.models.metrics import Metric, Report, ReportRun
from app.models.project import Project
from app.schemas.metrics import (
    MetricPage,
    MetricRead,
    MetricValue,
    ReportBody,
    ReportPage,
    ReportRead,
    ReportRunPage,
    ReportRunRead,
    ReportValue,
)
from app.services.import_service import _hidden_fields
from app.services.spec_service import SpecService
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)

MAX_METRICS = 100
MAX_REPORTS = 50
MAX_RECORDS = 50_000  # per metric computation; beyond it the metric is refused, never truncated
USAGE_METRIC = "reports.runs"


def _invalid(exc: mx.MetricError) -> AppError:
    return AppError(exc.code, str(exc), 422)


def _metric_read(m: Metric) -> MetricRead:
    return MetricRead(key=m.key, version=m.version, definition=m.definition, updated_at=m.updated_at)


def _second(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(microsecond=0)


def _used_fields(d: mx.MetricDef) -> set[str]:
    used = {f.field for f in d.filter}
    used.update(x for x in (d.field, d.group_by) if x is not None)
    return used


class MetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # -- shared lookups ----------------------------------------------------------------------

    async def _entity(self, project_id: uuid.UUID, name: str) -> SpecEntity | None:
        spec = await SpecService(self.s).assemble(project_id)  # 404 for an unknown project
        return next((e for e in spec.entities if e.name == name), None)

    async def _metric(self, project_id: uuid.UUID, key: str) -> Metric:
        m = (
            await self.s.execute(select(Metric).where(Metric.project_id == project_id, Metric.key == key))
        ).scalar_one_or_none()
        if m is None:
            raise AppError("not_found", "metric not found", 404)
        return m

    async def _report(self, project_id: uuid.UUID, report_id: uuid.UUID) -> Report:
        r = (
            await self.s.execute(
                select(Report).where(Report.id == report_id, Report.project_id == project_id)
            )
        ).scalar_one_or_none()
        if r is None:
            raise AppError("not_found", "report not found", 404)
        return r

    async def _records(self, project_id: uuid.UUID, entity: str) -> list[dict[str, Any]]:
        rows = (
            await self.s.execute(
                select(ImportedRecord.data)
                .where(ImportedRecord.project_id == project_id, ImportedRecord.entity_name == entity)
                .limit(MAX_RECORDS + 1)
            )
        ).scalars().all()
        if len(rows) > MAX_RECORDS:
            raise AppError(
                "metric_too_large", f"the entity has more than {MAX_RECORDS} records to aggregate", 422
            )
        return list(rows)

    async def _compute(
        self,
        project_id: uuid.UUID,
        m: Metric,
        cache: dict[str, list[dict[str, Any]]],
        role: str | None = None,
        enforce: bool = False,
    ) -> dict[str, Any]:
        """`enforce` = a person is asking as `role` (None fails closed): a metric that reads, filters
        or groups by a field that role may not read is refused (C7 field access). Scheduled runs
        compute as the system (enforce False) and are redacted per viewer when read."""
        d = mx.parse_metric(m.definition)
        entity = await self._entity(project_id, d.entity)
        mx.validate_metric(d, entity)  # the spec may have changed since the definition was saved
        if enforce and entity is not None:
            spec = await SpecService(self.s).assemble(project_id)
            if _used_fields(d) & _hidden_fields(spec, entity, role):
                raise AppError(
                    "field_access_denied", "the metric uses a field your role may not read", 403
                )
        if d.entity not in cache:
            cache[d.entity] = await self._records(project_id, d.entity)
        return mx.compute(d, cache[d.entity], entity).as_dict()

    # -- metrics CRUD ------------------------------------------------------------------------

    async def _checked(self, project_id: uuid.UUID, raw: dict[str, Any]) -> mx.MetricDef:
        try:
            d = mx.parse_metric(raw)
            mx.validate_metric(d, await self._entity(project_id, d.entity))
        except mx.MetricError as exc:
            raise _invalid(exc) from None
        return d

    async def list_metrics(self, project_id: uuid.UUID) -> MetricPage:
        await self._entity(project_id, "")  # 404 for an unknown project
        rows = (
            await self.s.execute(select(Metric).where(Metric.project_id == project_id).order_by(Metric.key))
        ).scalars().all()
        return MetricPage(items=[_metric_read(m) for m in rows], total=len(rows))

    async def get_metric(self, project_id: uuid.UUID, key: str) -> MetricRead:
        return _metric_read(await self._metric(project_id, key))

    async def create_metric(self, project_id: uuid.UUID, raw: dict[str, Any]) -> MetricRead:
        d = await self._checked(project_id, raw)
        count = (
            await self.s.execute(select(func.count()).select_from(Metric).where(Metric.project_id == project_id))
        ).scalar_one()
        if count >= MAX_METRICS:
            raise AppError("metrics_limit_reached", f"a project holds at most {MAX_METRICS} metrics", 409)
        m = Metric(project_id=project_id, key=d.key, definition=d.model_dump(), version=1)
        self.s.add(m)
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            raise AppError("metric_exists", f"the metric {d.key!r} already exists", 409) from None
        return _metric_read(m)

    async def update_metric(self, project_id: uuid.UUID, key: str, raw: dict[str, Any]) -> MetricRead:
        m = (
            await self.s.execute(
                select(Metric).where(Metric.project_id == project_id, Metric.key == key).with_for_update()
            )
        ).scalar_one_or_none()
        if m is None:
            raise AppError("not_found", "metric not found", 404)
        d = await self._checked(project_id, raw)
        if d.key != key:
            raise AppError("metric_invalid", "key: a metric's key cannot change; create a new metric", 422)
        m.definition = d.model_dump()
        m.version += 1
        await self.s.commit()
        return _metric_read(m)

    async def delete_metric(self, project_id: uuid.UUID, key: str) -> None:
        m = await self._metric(project_id, key)
        used = [
            r.name
            for r in (
                await self.s.execute(select(Report).where(Report.project_id == project_id))
            ).scalars()
            if key in r.metric_keys
        ]
        if used:
            raise AppError(
                "metric_in_use", f"the metric is used by report(s): {', '.join(sorted(used))[:200]}", 409
            )
        await self.s.delete(m)
        await self.s.commit()

    async def metric_value(
        self, project_id: uuid.UUID, key: str, role: str | None = None
    ) -> MetricValue:
        m = await self._metric(project_id, key)
        try:
            out = await self._compute(project_id, m, {}, role, True)
        except mx.MetricError as exc:
            raise _invalid(exc) from None
        return MetricValue(
            key=m.key, version=m.version, value=out["value"], groups=out.get("groups"),
            computed_at=datetime.now(UTC),
        )  # fmt: skip

    # -- reports CRUD ------------------------------------------------------------------------

    async def _check_report(self, project_id: uuid.UUID, body: ReportBody) -> None:
        try:
            jobs_cron.validate(body.schedule, body.timezone)
        except jobs_cron.CronError as exc:
            raise AppError("report_invalid", f"schedule: {exc}", 422) from None
        if len(set(body.metric_keys)) != len(body.metric_keys):
            raise AppError("report_invalid", "metric_keys: a metric is listed twice", 422)
        have = set(
            (await self.s.execute(select(Metric.key).where(Metric.project_id == project_id))).scalars()
        )
        missing = [k for k in body.metric_keys if k not in have]
        if missing:
            raise AppError("report_invalid", f"metric_keys: unknown metric {missing[0][:60]!r}", 422)

    async def list_reports(self, project_id: uuid.UUID) -> ReportPage:
        await self._entity(project_id, "")
        rows = (
            await self.s.execute(
                select(Report).where(Report.project_id == project_id).order_by(Report.created_at, Report.id)
            )
        ).scalars().all()
        return ReportPage(items=[ReportRead.model_validate(r) for r in rows], total=len(rows))

    async def get_report(self, project_id: uuid.UUID, report_id: uuid.UUID) -> ReportRead:
        return ReportRead.model_validate(await self._report(project_id, report_id))

    async def create_report(self, project_id: uuid.UUID, body: ReportBody) -> ReportRead:
        await self._entity(project_id, "")
        await self._check_report(project_id, body)
        count = (
            await self.s.execute(select(func.count()).select_from(Report).where(Report.project_id == project_id))
        ).scalar_one()
        if count >= MAX_REPORTS:
            raise AppError("reports_limit_reached", f"a project holds at most {MAX_REPORTS} reports", 409)
        r = Report(
            project_id=project_id, name=body.name, metric_keys=list(body.metric_keys),
            schedule=body.schedule, timezone=body.timezone, enabled=body.enabled,
            last_scheduled_for=datetime.now(UTC),
        )  # fmt: skip
        self.s.add(r)
        await self.s.commit()
        return ReportRead.model_validate(r)

    async def update_report(
        self, project_id: uuid.UUID, report_id: uuid.UUID, body: ReportBody
    ) -> ReportRead:
        r = await self._report(project_id, report_id)
        await self._check_report(project_id, body)
        if (body.enabled and not r.enabled) or (body.schedule, body.timezone) != (r.schedule, r.timezone):
            r.last_scheduled_for = datetime.now(UTC)  # no retroactive firing of older slots
        r.name, r.metric_keys = body.name, list(body.metric_keys)
        r.schedule, r.timezone, r.enabled = body.schedule, body.timezone, body.enabled
        await self.s.commit()
        return ReportRead.model_validate(r)

    async def delete_report(self, project_id: uuid.UUID, report_id: uuid.UUID) -> None:
        await self.s.delete(await self._report(project_id, report_id))
        await self.s.commit()

    # -- values and runs ---------------------------------------------------------------------

    async def _values(
        self, report: Report, role: str | None = None, enforce: bool = False
    ) -> dict[str, Any]:
        cache: dict[str, list[dict[str, Any]]] = {}
        out: dict[str, Any] = {}
        metrics = {
            m.key: m
            for m in (
                await self.s.execute(
                    select(Metric).where(Metric.project_id == report.project_id, Metric.key.in_(report.metric_keys))
                )
            ).scalars()
        }
        for key in report.metric_keys:
            m = metrics.get(key)
            if m is None:
                out[key] = {"error": "metric_missing"}
                continue
            try:
                res = await self._compute(report.project_id, m, cache, role, enforce)
            except (mx.MetricError, AppError) as exc:
                code = exc.code
                out[key] = {"version": m.version, "error": code}
                continue
            out[key] = {"value": res["value"], "version": m.version}
            if "groups" in res:
                out[key]["groups"] = res["groups"]
        return out

    async def report_value(
        self, project_id: uuid.UUID, report_id: uuid.UUID, role: str | None = None
    ) -> ReportValue:
        r = await self._report(project_id, report_id)
        return ReportValue(
            report_id=r.id, values=await self._values(r, role, True), computed_at=datetime.now(UTC)
        )

    async def _redact(
        self, project_id: uuid.UUID, runs: list[ReportRunRead], role: str | None
    ) -> list[ReportRunRead]:
        """Stored values were computed as the system; hide the ones the viewer may not read."""
        keys = {k for r in runs for k in r.values if isinstance(r.values.get(k), dict)}
        if not keys:
            return runs
        spec = await SpecService(self.s).assemble(project_id)
        metrics = (
            await self.s.execute(select(Metric).where(Metric.project_id == project_id, Metric.key.in_(keys)))
        ).scalars()
        denied: set[str] = set()
        found: dict[str, Any] = {}
        for m in metrics:
            found[m.key] = m
            try:
                d = mx.parse_metric(m.definition)
            except mx.MetricError:
                denied.add(m.key)
                continue
            ent = next((e for e in spec.entities if e.name == d.entity), None)
            if ent is None or _used_fields(d) & _hidden_fields(spec, ent, role):
                denied.add(m.key)
        for r in runs:
            # a metric deleted since, or edited after the run was stored, may have read a field the
            # current definition no longer shows: fail closed for that run's value
            gone = {k for k in keys if k not in found}
            stale = {k for k, m in found.items() if m.updated_at and r.created_at and m.updated_at > r.created_at}
            hide = denied | gone | stale
            r.values = {
                k: ({"error": "field_access_denied"} if k in hide and isinstance(v, dict) else v)
                for k, v in r.values.items()
            }
        return runs

    async def list_runs(
        self,
        project_id: uuid.UUID,
        report_id: uuid.UUID,
        limit: int,
        offset: int,
        role: str | None = None,
    ) -> ReportRunPage:
        await self._report(project_id, report_id)
        q = select(ReportRun).where(ReportRun.report_id == report_id)
        total = (await self.s.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (
            await self.s.execute(q.order_by(ReportRun.scheduled_for.desc()).limit(limit).offset(offset))
        ).scalars().all()
        items = await self._redact(project_id, [ReportRunRead.model_validate(x) for x in rows], role)
        return ReportRunPage(items=items, total=total, limit=limit, offset=offset)

    async def _store_run(
        self, report: Report, org_id: uuid.UUID, slot: datetime, *, refuse_raises: bool
    ) -> ReportRun | None:
        """Insert the run for `slot` once (None when it already exists), meter it, fill its values."""
        run_id = (
            await self.s.execute(
                pg_insert(ReportRun)
                .values(
                    id=uuid.uuid4(), report_id=report.id, project_id=report.project_id,
                    scheduled_for=slot, status="running", values={}, created_at=datetime.now(UTC),
                )  # fmt: skip
                .on_conflict_do_nothing(index_elements=["report_id", "scheduled_for"])
                .returning(ReportRun.id)
            )
        ).scalar_one_or_none()
        if run_id is None:
            return None
        run = await self.s.get(ReportRun, run_id)
        assert run is not None
        try:
            await UsageService(self.s).consume(
                org_id, USAGE_METRIC, 1, project_id=report.project_id,
                idempotency_key=f"{report.id}:{slot.isoformat()}",
            )  # fmt: skip
        except AppError as exc:
            if exc.code != "quota_exceeded" or refuse_raises:
                raise
            run.status = "refused"
            run.values = {"error": "quota_exceeded"}
            return run
        run.values = await self._values(report)
        run.status = "ok"
        return run

    async def run_now(
        self, project_id: uuid.UUID, report_id: uuid.UUID, role: str | None = None
    ) -> ReportRunRead:
        """Manual run, stored under the current second as its slot (a repeat in the same second
        returns the stored run)."""
        r = await self._report(project_id, report_id)
        org_id = (
            await self.s.execute(select(Project.organization_id).where(Project.id == project_id))
        ).scalar_one()
        slot = _second(datetime.now(UTC))
        try:
            run = await self._store_run(r, org_id, slot, refuse_raises=True)
        except AppError:
            await self.s.rollback()
            raise
        if run is None:
            run = (
                await self.s.execute(
                    select(ReportRun).where(ReportRun.report_id == r.id, ReportRun.scheduled_for == slot)
                )
            ).scalar_one()
        await self.s.commit()
        return (await self._redact(project_id, [ReportRunRead.model_validate(run)], role))[0]


async def fire_due_reports(session: AsyncSession, now: datetime) -> int:
    """Store the latest due slot of every enabled report; returns how many runs THIS call stored.

    Safe to call from many schedulers at once and any number of times with the same `now`.
    Commits after each report so one failing report does not undo the others.
    """
    if now.tzinfo is None:
        raise ValueError("fire_due_reports needs a timezone-aware now")
    now = now.astimezone(UTC)
    svc = MetricsService(session)
    rows = (
        await session.execute(
            select(Report.id, Project.organization_id)
            .join(Project, Project.id == Report.project_id)
            .where(Report.enabled.is_(True))
            .order_by(Report.id)
        )
    ).all()
    fired = 0
    for report_id, org_id in rows:
        report = await session.get(Report, report_id, populate_existing=True)
        if report is None or not report.enabled:
            continue
        try:
            spec = jobs_cron.parse(report.schedule)
            slot = jobs_cron.previous_fire(spec, jobs_cron.zone(report.timezone), now)
        except jobs_cron.CronError:
            continue  # validated on save; a bad row must not stop the others
        last = report.last_scheduled_for
        if slot is None or (last is not None and slot <= last):
            continue
        try:
            run = await svc._store_run(report, org_id, slot, refuse_raises=False)
            await session.execute(
                update(Report)
                .where(Report.id == report.id)
                .where((Report.last_scheduled_for.is_(None)) | (Report.last_scheduled_for < slot))
                .values(last_scheduled_for=slot)
            )
            await session.commit()
        except Exception:
            # one failing report must not starve the ones after it; it retries on the next run
            await session.rollback()
            logger.exception("report %s failed to fire", report_id)
            continue
        if run is not None:
            fired += 1
    return fired
