"""Metrics layer and scheduled reports (B4-4, C22).

GET    /projects/{project_id}/metrics                      (viewer)
POST   /projects/{project_id}/metrics                      {definition} (editor)
GET    /projects/{project_id}/metrics/{key}                (viewer)
PUT    /projects/{project_id}/metrics/{key}                {definition}; bumps version (editor)
DELETE /projects/{project_id}/metrics/{key}                refused while a report uses it (editor)
GET    /projects/{project_id}/metrics/{key}/value          live computation (viewer)
GET/POST /projects/{project_id}/reports                    (viewer / editor)
GET/PUT/DELETE /projects/{project_id}/reports/{report_id}
POST   /projects/{project_id}/reports/{report_id}/run      manual run, stored (editor)
GET    /projects/{project_id}/reports/{report_id}/runs     (viewer)
GET    /projects/{project_id}/reports/{report_id}/value    live values of its metrics (viewer)
"""

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.metrics import (
    MetricBody,
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
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/projects/{project_id}", tags=["metrics"])


@router.get("/metrics", response_model=MetricPage)
async def list_metrics(project_id: uuid.UUID, db: AsyncSession = Depends(get_session)) -> MetricPage:
    return await MetricsService(db).list_metrics(project_id)


@router.post("/metrics", response_model=MetricRead, status_code=201)
async def create_metric(
    project_id: uuid.UUID, body: MetricBody, db: AsyncSession = Depends(get_session)
) -> MetricRead:
    return await MetricsService(db).create_metric(project_id, body.definition)


@router.get("/metrics/{key}", response_model=MetricRead)
async def get_metric(project_id: uuid.UUID, key: str, db: AsyncSession = Depends(get_session)) -> MetricRead:
    return await MetricsService(db).get_metric(project_id, key)


@router.put("/metrics/{key}", response_model=MetricRead)
async def put_metric(
    project_id: uuid.UUID, key: str, body: MetricBody, db: AsyncSession = Depends(get_session)
) -> MetricRead:
    return await MetricsService(db).update_metric(project_id, key, body.definition)


@router.delete("/metrics/{key}", status_code=204)
async def delete_metric(
    project_id: uuid.UUID, key: str, db: AsyncSession = Depends(get_session)
) -> Response:
    await MetricsService(db).delete_metric(project_id, key)
    return Response(status_code=204)


@router.get("/metrics/{key}/value", response_model=MetricValue)
async def metric_value(
    project_id: uuid.UUID, key: str, db: AsyncSession = Depends(get_session)
) -> MetricValue:
    return await MetricsService(db).metric_value(project_id, key)


@router.get("/reports", response_model=ReportPage)
async def list_reports(project_id: uuid.UUID, db: AsyncSession = Depends(get_session)) -> ReportPage:
    return await MetricsService(db).list_reports(project_id)


@router.post("/reports", response_model=ReportRead, status_code=201)
async def create_report(
    project_id: uuid.UUID, body: ReportBody, db: AsyncSession = Depends(get_session)
) -> ReportRead:
    return await MetricsService(db).create_report(project_id, body)


@router.get("/reports/{report_id}", response_model=ReportRead)
async def get_report(
    project_id: uuid.UUID, report_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> ReportRead:
    return await MetricsService(db).get_report(project_id, report_id)


@router.put("/reports/{report_id}", response_model=ReportRead)
async def put_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    body: ReportBody,
    db: AsyncSession = Depends(get_session),
) -> ReportRead:
    return await MetricsService(db).update_report(project_id, report_id, body)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    project_id: uuid.UUID, report_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> Response:
    await MetricsService(db).delete_report(project_id, report_id)
    return Response(status_code=204)


@router.post("/reports/{report_id}/run", response_model=ReportRunRead)
async def run_report(
    project_id: uuid.UUID, report_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> ReportRunRead:
    return await MetricsService(db).run_now(project_id, report_id)


@router.get("/reports/{report_id}/runs", response_model=ReportRunPage)
async def list_runs(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> ReportRunPage:
    return await MetricsService(db).list_runs(project_id, report_id, limit, offset)


@router.get("/reports/{report_id}/value", response_model=ReportValue)
async def report_value(
    project_id: uuid.UUID, report_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> ReportValue:
    return await MetricsService(db).report_value(project_id, report_id)
