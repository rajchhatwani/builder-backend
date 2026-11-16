"""Request and response models of the geo API (generated). Coordinates: see app/operations/points.py."""

import datetime as dt
import typing as _t
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.operations.points import Point, PointOut

Shape = _t.Literal["circle", "polygon"]
Mode = _t.Literal["drive", "walk", "bike"]


class PlaceCreate(Point):
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = Field(default=None, max_length=32)


class PlaceOut(PointOut):
    id: uuid.UUID
    name: str
    kind: str | None
    created_at: dt.datetime


class PlaceHit(PlaceOut):
    distance_m: int


class PlaceHits(BaseModel):
    items: list[PlaceHit]
    truncated: bool = False


class GeofenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    shape: Shape
    center: Point | None = None
    radius_m: StrictInt | None = Field(default=None, ge=1)
    vertices: list[Point] | None = Field(default=None, min_length=3)

    @model_validator(mode="after")
    def _shape(self) -> "GeofenceCreate":
        if self.shape == "circle" and (self.center is None or self.radius_m is None or self.vertices is not None):
            raise ValueError("a circle needs center and radius_m (and no vertices)")
        if self.shape == "polygon" and (self.vertices is None or self.center is not None or self.radius_m is not None):
            raise ValueError("a polygon needs vertices (and no center or radius_m)")
        return self


class GeofenceOut(BaseModel):
    id: uuid.UUID
    name: str
    shape: Shape
    center: PointOut | None
    radius_m: int | None
    vertices: list[PointOut] | None
    created_at: dt.datetime


class Geofences(BaseModel):
    items: list[GeofenceOut]


class ContainsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: Point


class DistanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: Point
    b: Point


class DistanceOut(BaseModel):
    distance_m: int


class EvaluateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1, max_length=128)
    point: Point


class FenceEventOut(BaseModel):
    id: uuid.UUID
    subject_id: str
    geofence_id: uuid.UUID
    geofence_name: str
    event: _t.Literal["enter", "exit"]
    lat_micro: int
    lng_micro: int
    occurred_at: dt.datetime


class EvaluateOut(BaseModel):
    inside: list[uuid.UUID]
    events: list[FenceEventOut]


class GeocodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=1, max_length=300)


class GeocodeOut(PointOut):
    provider: str


class RouteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Point
    destination: Point
    mode: Mode = "drive"


class RouteOut(BaseModel):
    distance_m: int
    duration_s: int
    mode: Mode
    provider: str


class EtaIn(RouteIn):
    depart_at: dt.datetime | None = None

    @field_validator("depart_at")
    @classmethod
    def _depart_in_range(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return value
        now = dt.datetime.now(dt.UTC)
        aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
        if abs(aware - now) > dt.timedelta(days=3650):
            raise ValueError("depart_at must be within 10 years of now")
        return value


class EtaOut(BaseModel):
    duration_s: int
    distance_m: int
    arrives_at: dt.datetime
    provider: str
