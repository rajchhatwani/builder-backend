"""Request and response models of the location API (generated). Coordinates: see app/operations/points.py."""

import datetime as dt
import typing as _t
import uuid

from pydantic import BaseModel, Field, StrictInt

from app.operations.points import Point, PointOut

SEQ_MAX = 2**62
NO_NUL_PATTERN = r"^[^\x00]*$"  # Postgres text cannot hold NUL: refuse it with a 422, not a 500
SUBJECT_ID_PATTERN = r"^[^/\x00]+$"  # no "/" or NUL: the id is one path segment of GET /positions/{subject_id}


class PositionIn(Point):
    subject_id: str = Field(min_length=1, max_length=128, pattern=SUBJECT_ID_PATTERN)
    subject_kind: str | None = Field(default=None, max_length=32, pattern=NO_NUL_PATTERN)
    seq: StrictInt = Field(ge=0, le=SEQ_MAX)
    recorded_at: dt.datetime | None = None


class PositionOut(PointOut):
    subject_id: str
    subject_kind: str | None
    seq: int
    recorded_at: dt.datetime
    updated_at: dt.datetime


class FenceEvent(BaseModel):
    id: uuid.UUID
    subject_id: str
    geofence_id: uuid.UUID
    geofence_name: str
    event: str
    lat_micro: int
    lng_micro: int
    occurred_at: dt.datetime


class PositionResult(BaseModel):
    applied: bool
    reason: _t.Literal["stale"] | None = None
    position: PositionOut
    geofence_events: list[FenceEvent] = []


class HistoryRow(PointOut):
    subject_id: str
    seq: int
    recorded_at: dt.datetime


class HistoryOut(BaseModel):
    items: list[HistoryRow]
    retention_cap: int


class BoxOut(BaseModel):
    items: list[PositionOut]
    truncated: bool
