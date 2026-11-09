import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UsageMetricRead(BaseModel):
    metric: str
    unit: str
    period: str
    period_start: datetime | None
    period_end: datetime | None
    used: int
    limit: int | None
    refused: int


class UsageSummaryRead(BaseModel):
    metrics: list[UsageMetricRead]


class UsageLimitWrite(BaseModel):
    limit_value: int | None = Field(default=None, ge=0)  # null = unlimited


class UsageEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    metric: str
    amount: int
    outcome: str
    created_at: datetime


class UsageEventPage(BaseModel):
    items: list[UsageEventRead]
    total: int
    limit: int
    offset: int
