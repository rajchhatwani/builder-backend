"""Coordinates in requests and responses (generated). Internally and on the wire the truth is integer
micro-degrees (`lat_micro`, `lng_micro`); decimal degrees (`lat`, `lng`) are accepted as Decimal / strings (more
than 6 decimals are rounded half to even) and returned as 6-decimal strings."""

import typing as _t
from decimal import ROUND_HALF_EVEN, Decimal

from pydantic import BaseModel, ConfigDict, StrictInt, model_validator

from app.core.errors import AppError
from app.operations.geomath import MAX_LAT_MICRO, MAX_LNG_MICRO, MICRO, valid_coordinates

_BIG = Decimal(1000)


def to_micro(value: Decimal) -> int:
    if value.is_nan() or value.is_infinite() or abs(value) > _BIG:
        raise AppError("invalid_coordinates", "a coordinate is a plain decimal number of degrees", 422)
    return int((value * MICRO).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def degrees_text(micro: int) -> str:
    sign = "-" if micro < 0 else ""
    return f"{sign}{abs(micro) // MICRO}.{abs(micro) % MICRO:06d}"


def resolve(lat_micro: int | None, lng_micro: int | None, lat: Decimal | None, lng: Decimal | None) -> tuple[int, int]:
    """(lat_micro, lng_micro) from exactly one pair of fields. Refusals are AppErrors (422 `invalid_point` /
    `invalid_coordinates`): they are not ValueErrors, so they pass through pydantic and keep their own code."""
    micro = lat_micro is not None or lng_micro is not None
    deg = lat is not None or lng is not None
    if micro == deg:
        raise AppError("invalid_point", "give either lat_micro + lng_micro or lat + lng", 422)
    if micro:
        if lat_micro is None or lng_micro is None:
            raise AppError("invalid_point", "lat_micro and lng_micro go together", 422)
        la, ln = lat_micro, lng_micro
    else:
        if lat is None or lng is None:
            raise AppError("invalid_point", "lat and lng go together", 422)
        la, ln = to_micro(lat), to_micro(lng)
    if not valid_coordinates(la, ln):
        raise AppError(
            "invalid_coordinates",
            f"latitude must be within -90..90 and longitude within -180..180 degrees ({MAX_LAT_MICRO}, {MAX_LNG_MICRO} micro)",
            422,
        )
    return la, ln


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat_micro: StrictInt | None = None
    lng_micro: StrictInt | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None

    @model_validator(mode="after")
    def _check(self) -> "Point":
        resolve(self.lat_micro, self.lng_micro, self.lat, self.lng)
        return self

    @property
    def micro(self) -> tuple[int, int]:
        return resolve(self.lat_micro, self.lng_micro, self.lat, self.lng)


def query_point(lat_micro: int | None, lng_micro: int | None, lat: str | None, lng: str | None) -> tuple[int, int]:
    """A point from query-string values; 422 `invalid_point`."""
    try:
        la = Decimal(lat) if lat is not None else None
        ln = Decimal(lng) if lng is not None else None
    except ArithmeticError as exc:
        raise AppError("invalid_point", "lat and lng must be decimal numbers", 422) from exc
    return resolve(lat_micro, lng_micro, la, ln)


def coords(lat_micro: int, lng_micro: int) -> dict[str, _t.Any]:
    return {"lat_micro": lat_micro, "lng_micro": lng_micro, "lat": degrees_text(lat_micro), "lng": degrees_text(lng_micro)}


class PointOut(BaseModel):
    lat_micro: int
    lng_micro: int
    lat: str
    lng: str

    @classmethod
    def of(cls, lat_micro: int, lng_micro: int) -> "PointOut":
        return cls(**coords(lat_micro, lng_micro))
