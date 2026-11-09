"""Schemas for the metrics layer and scheduled reports (B4-4)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MetricBody(BaseModel):
    """`definition` is parsed by app.core.metrics so every defect is the stable `metric_invalid`."""

    definition: dict[str, Any]


class MetricRead(BaseModel):
    key: str
    version: int
    definition: dict[str, Any]
    updated_at: datetime


class MetricPage(BaseModel):
    items: list[MetricRead]
    total: int


class MetricValue(BaseModel):
    key: str
    version: int
    value: int | str | None
    groups: list[dict[str, Any]] | None = None
    computed_at: datetime


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    metric_keys: list[str] = Field(min_length=1, max_length=20)
    schedule: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    enabled: bool = True


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    metric_keys: list[str]
    schedule: str
    timezone: str
    enabled: bool
    last_scheduled_for: datetime | None
    updated_at: datetime


class ReportPage(BaseModel):
    items: list[ReportRead]
    total: int


class ReportRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_id: uuid.UUID
    scheduled_for: datetime
    status: str
    values: dict[str, Any]
    created_at: datetime


class ReportRunPage(BaseModel):
    items: list[ReportRunRead]
    total: int
    limit: int
    offset: int


class ReportValue(BaseModel):
    report_id: uuid.UUID
    values: dict[str, Any]
    computed_at: datetime
