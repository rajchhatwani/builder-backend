"""Request and response models of the matching API (generated). Scores, distances and loads are strict integers."""

import datetime as dt
import typing as _t
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.operations.matching import config as _config
from app.operations.points import Point, resolve

NO_NUL_PATTERN = r"^[^\x00]*$"  # Postgres text cannot hold NUL: refuse it with a 422, not a 500
Status = _t.Literal["offered", "accepted", "rejected", "expired"]


class CandidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128, pattern=NO_NUL_PATTERN)
    lat_micro: StrictInt | None = None
    lng_micro: StrictInt | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    load: StrictInt = Field(default=0, ge=0, le=1_000_000_000)
    rating_milli: StrictInt = Field(default=0, ge=0, le=5000)

    @model_validator(mode="after")
    def _point(self) -> "CandidateIn":
        if any(v is not None for v in (self.lat_micro, self.lng_micro, self.lat, self.lng)):
            resolve(self.lat_micro, self.lng_micro, self.lat, self.lng)
        return self

    @property
    def micro(self) -> tuple[int, int] | None:
        if all(v is None for v in (self.lat_micro, self.lng_micro, self.lat, self.lng)):
            return None
        return resolve(self.lat_micro, self.lng_micro, self.lat, self.lng)


class RankIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: Point
    candidates: list[CandidateIn] = Field(min_length=1, max_length=_config.MAX_CANDIDATES)

    @model_validator(mode="after")
    def _unique_candidates(self) -> "RankIn":
        ids = [c.id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("a candidate id is listed twice")
        return self


class Parts(BaseModel):
    distance: int
    load: int
    rating: int


class RankedOut(BaseModel):
    candidate_id: str
    score: int
    distance_m: int
    parts: Parts


class ExcludedOut(BaseModel):
    candidate_id: str
    reason: str


class RankOut(BaseModel):
    items: list[RankedOut]
    excluded: list[ExcludedOut]


class AssignIn(RankIn):
    request_ref: str = Field(min_length=1, max_length=128, pattern=NO_NUL_PATTERN)


class AssignmentOut(BaseModel):
    id: uuid.UUID
    request_ref: str
    candidate_id: str
    status: Status
    score: int
    distance_m: int
    offered_at: dt.datetime
    expires_at: dt.datetime
    decided_at: dt.datetime | None
    decided_by: uuid.UUID | None


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_ref: str = Field(min_length=1, max_length=128, pattern=NO_NUL_PATTERN)
    point: Point


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: list[BatchRequest] = Field(min_length=1, max_length=_config.MAX_BATCH_REQUESTS)
    candidates: list[CandidateIn] = Field(min_length=1, max_length=_config.MAX_CANDIDATES)
    commit: bool = False

    @model_validator(mode="after")
    def _unique(self) -> "BatchIn":
        refs = [r.request_ref for r in self.requests]
        if len(set(refs)) != len(refs):
            raise ValueError("a request_ref is listed twice")
        ids = [c.id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("a candidate id is listed twice")
        return self


class PairOut(BaseModel):
    request_ref: str
    candidate_id: str
    score: int
    distance_m: int


class BatchOut(BaseModel):
    pairs: list[PairOut]
    unassigned: list[str]
    skipped: list[str]
    total_score: int
    solver: _t.Literal["optimal", "greedy"]
    assignments: list[AssignmentOut]


class ExpireOut(BaseModel):
    expired: int
