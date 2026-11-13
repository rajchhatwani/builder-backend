"""Geocoder, routing and ETA adapters (generated). An adapter is an interface (Protocol) plus a provider; the only
provider shipped is the deterministic FAKE one below: no outbound call is ever made. A real provider is a class
with the same methods, registered in PROVIDERS (a custom extension; the spec refuses any other `provider`)."""

import hashlib
import typing as _t
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.operations.geomath import haversine_m

MODES = ("drive", "walk", "bike")
# fake road model: distance = straight line x 13 / 10; speeds in decimetres per second (50, 5 and 16 km/h)
_DETOUR_NUM, _DETOUR_DEN = 13, 10
_SPEED_DM_S = {"drive": 139, "walk": 14, "bike": 45}


@dataclass(frozen=True)
class GeocodeResult:
    lat_micro: int
    lng_micro: int


@dataclass(frozen=True)
class RouteResult:
    distance_m: int
    duration_s: int


@dataclass(frozen=True)
class EtaResult:
    duration_s: int
    distance_m: int
    arrives_at: datetime


class Geocoder(_t.Protocol):
    def geocode(self, address: str) -> GeocodeResult: ...


class Router(_t.Protocol):
    def route(self, origin: tuple[int, int], destination: tuple[int, int], mode: str) -> RouteResult: ...


class EtaProvider(_t.Protocol):
    def eta(self, origin: tuple[int, int], destination: tuple[int, int], mode: str, depart_at: datetime | None) -> EtaResult: ...


class FakeGeocoder:
    """The same address (trimmed, case-insensitive) always gives the same point, inside +-60 / +-170 degrees."""

    def geocode(self, address: str) -> GeocodeResult:
        digest = hashlib.sha256(" ".join(address.lower().split()).encode()).digest()
        lat = int.from_bytes(digest[0:4], "big") % 120_000_001 - 60_000_000
        lng = int.from_bytes(digest[4:8], "big") % 340_000_001 - 170_000_000
        return GeocodeResult(lat, lng)


class FakeRouter:
    def route(self, origin: tuple[int, int], destination: tuple[int, int], mode: str) -> RouteResult:
        distance = (haversine_m(*origin, *destination) * _DETOUR_NUM + _DETOUR_DEN // 2) // _DETOUR_DEN
        speed = _SPEED_DM_S[mode]
        return RouteResult(distance, (distance * 10 + speed // 2) // speed)


class FakeEta:
    def __init__(self, router: Router) -> None:
        self._router = router

    def eta(self, origin: tuple[int, int], destination: tuple[int, int], mode: str, depart_at: datetime | None) -> EtaResult:
        route = self._router.route(origin, destination, mode)
        start = depart_at or datetime.now(UTC)
        return EtaResult(route.duration_s, route.distance_m, start + timedelta(seconds=route.duration_s))


class Providers(_t.NamedTuple):
    geocoder: Geocoder
    router: Router
    eta: EtaProvider


def _fake() -> Providers:
    router = FakeRouter()
    return Providers(FakeGeocoder(), router, FakeEta(router))


PROVIDERS: dict[str, _t.Callable[[], Providers]] = {"fake": _fake}


def providers(name: str) -> Providers:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise RuntimeError(f"unknown geo provider {name!r}") from None
