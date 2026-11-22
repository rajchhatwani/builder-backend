"""Scenario tests for the operations pack (D13 geo, D14 location, D15 matching, D16 prediction) in the generated
`operations_fleet` project (copied into the project's tests/ by tests/e2e/test_operations_stack.py, run against a real
Postgres). Spec: multi-tenant rbac; roles admin, dispatcher, driver; geo read admin/dispatcher/driver, write
admin/dispatcher (max 20 geofences, 12 vertices); location read everyone, write everyone (history cap 5); matching
admin/dispatcher (weights 600/300/100, max distance 20 km, max load 5, offer TTL 300 s); prediction admin/dispatcher
(fake predictor, unit minutes, interval 2000 bp).

Proves: places within / nearest, circle and polygon fences, contains, distance, enter / exit evaluation decided by the
database (8 parallel evaluations give one enter), fake geocode / route / eta; a stale seq never overwrites a newer one
(8 parallel posts: the final position is the max seq), the history cap, the antimeridian box, fence events from
positions; ranking, assignment states, 8 parallel assigns give one 201 and seven 409, batch; predictions, idempotent
actuals (parallel too), stats (MAE and coverage); tenant isolation; roles. Every response is below 500."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient, Response

from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401

LAT, LNG = 52_500_000, 13_400_000  # the base point; 1000 micro-degrees of latitude is about 111 metres


async def _no_server_error(response: Response) -> None:
    assert response.status_code < 500, (response.request.url, response.text)


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", event_hooks={"response": [_no_server_error]}) as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "admin": await sign_in(http, "a@example.com", roles=["admin"], n=0),
        "disp": await sign_in(http, "a_disp@example.com", roles=["dispatcher"], n=1, join="a@example.com"),
        "driver": await sign_in(http, "a_driver@example.com", roles=["driver"], n=2, join="a@example.com"),
        "nobody": await sign_in(http, "a_nobody@example.com", roles=[], n=3, join="a@example.com"),
        "b_admin": await sign_in(http, "b@example.com", roles=["admin"], n=4),
    }


def pt(lat: int = LAT, lng: int = LNG) -> dict[str, int]:
    return {"lat_micro": lat, "lng_micro": lng}


def error_shape(r: Response) -> str:
    body = r.json()
    assert set(body) == {"code", "message", "details"} and isinstance(body["details"], list), body
    return body["code"]


async def scalar(sql: str, **params: object) -> object:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one()


async def execute(sql: str, **params: object) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(sql), params)
        await session.commit()


async def place(http: AsyncClient, who: dict[str, str], name: str, lat: int, lng: int, kind: str | None = None) -> dict:
    r = await http.post("/geo/places", json={"name": name, "kind": kind, **pt(lat, lng)}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


async def circle(http: AsyncClient, who: dict[str, str], name: str, lat: int, lng: int, radius_m: int) -> dict:
    r = await http.post("/geo/geofences", json={"name": name, "shape": "circle", "center": pt(lat, lng), "radius_m": radius_m}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


# --- D13 geo: places -----------------------------------------------------------------------------------------


async def test_places_are_created_listed_and_validated(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    p = await place(http, admin, "Depot", LAT, LNG, "depot")
    assert (p["lat_micro"], p["lng_micro"], p["lat"], p["lng"], p["kind"]) == (LAT, LNG, "52.500000", "13.400000", "depot")
    # decimal degrees: exact and rounded half to even
    r = await http.post("/geo/places", json={"name": "Dec", "lat": "52.1234565", "lng": "-1.5"}, headers=admin)
    assert r.status_code == 201 and (r.json()["lat_micro"], r.json()["lng_micro"], r.json()["lng"]) == (52_123_456, -1_500_000, "-1.500000"), r.text
    r = await http.post("/geo/places", json={"name": "Num", "lat": 10.25, "lng": 20}, headers=admin)
    assert r.status_code == 201 and r.json()["lat_micro"] == 10_250_000
    for body, code in (
        ({"name": "x"}, "invalid_point"),
        ({"name": "x", "lat_micro": 1}, "invalid_point"),
        ({"name": "x", "lat_micro": 1, "lng_micro": 1, "lat": "1", "lng": "1"}, "invalid_point"),
        ({"name": "x", "lat_micro": 90_000_001, "lng_micro": 0}, "invalid_coordinates"),
        ({"name": "x", "lat": "0", "lng": "181"}, "invalid_coordinates"),
        ({"name": "x", "lat_micro": 1.5, "lng_micro": 1}, "validation_error"),
        ({"name": "", "lat_micro": 1, "lng_micro": 1}, "validation_error"),
        ({"name": "x", "lat_micro": 1, "lng_micro": 1, "colour": "red"}, "validation_error"),
    ):
        r = await http.post("/geo/places", json=body, headers=admin)
        assert r.status_code == 422 and error_shape(r) == code, (body, r.text)
    page = (await http.get("/geo/places", params={"limit": 2}, headers=admin)).json()
    assert page["total"] == 3 and page["limit"] == 2 and [i["name"] for i in page["items"]] == ["Dec", "Depot"]
    assert (await http.get("/geo/places", params={"kind": "depot"}, headers=admin)).json()["total"] == 1
    got = await http.get(f"/geo/places/{p['id']}", headers=people["driver"])
    assert got.status_code == 200 and got.json()["id"] == p["id"]
    assert (await http.get("/geo/places", params={"limit": 0}, headers=admin)).status_code == 422
    assert (await http.delete(f"/geo/places/{p['id']}", headers=admin)).status_code == 204
    r = await http.delete(f"/geo/places/{p['id']}", headers=admin)
    assert r.status_code == 404 and error_shape(r) == "not_found"
    assert (await http.get(f"/geo/places/{p['id']}", headers=admin)).status_code == 404


async def test_within_and_nearest_order_by_distance_then_id(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    here = await place(http, admin, "here", LAT, LNG, "depot")
    near = await place(http, admin, "near", LAT + 1000, LNG, "depot")  # about 111 m
    mid = await place(http, admin, "mid", LAT + 5000, LNG, "shop")  # about 556 m
    far = await place(http, admin, "far", LAT + 50_000, LNG, "shop")  # about 5.6 km
    away = await place(http, admin, "away", LAT + 3_000_000, LNG, "shop")  # about 334 km
    q = {**pt(), "radius_m": 600}
    hits = (await http.get("/geo/places/within", params=q, headers=people["driver"])).json()
    assert [h["id"] for h in hits["items"]] == [here["id"], near["id"], mid["id"]] and hits["truncated"] is False
    assert [h["distance_m"] for h in hits["items"]] == [0, 111, 556] and all(type(h["distance_m"]) is int for h in hits["items"])
    limited = (await http.get("/geo/places/within", params={**q, "limit": 2}, headers=admin)).json()
    assert len(limited["items"]) == 2 and limited["truncated"] is True
    assert [h["id"] for h in (await http.get("/geo/places/within", params={**q, "kind": "shop"}, headers=admin)).json()["items"]] == [mid["id"]]
    dec = (await http.get("/geo/places/within", params={"lat": "52.5", "lng": "13.4", "radius_m": 150}, headers=admin)).json()
    assert [h["id"] for h in dec["items"]] == [here["id"], near["id"]]
    nearest = (await http.get("/geo/places/nearest", params={**pt(), "n": 2}, headers=admin)).json()
    assert [h["id"] for h in nearest["items"]] == [here["id"], near["id"]]
    every = (await http.get("/geo/places/nearest", params={**pt(), "n": 5}, headers=admin)).json()
    assert [h["id"] for h in every["items"]] == [here["id"], near["id"], mid["id"], far["id"], away["id"]]  # widens until n are found
    assert [h["id"] for h in (await http.get("/geo/places/nearest", params={**pt(), "n": 1, "kind": "shop"}, headers=admin)).json()["items"]] == [mid["id"]]
    for path, params in (
        ("within", {"radius_m": 10}),
        ("within", {**pt(), "radius_m": 0}),
        ("within", {**pt(), "radius_m": 5_000_001}),
        ("within", {**pt(), "radius_m": 10, "lat": "1"}),
        ("within", {"lat": "x", "lng": "1", "radius_m": 10}),
        ("nearest", {**pt(), "n": 0}),
        ("nearest", {**pt(), "n": 51}),
        ("nearest", {"lat_micro": 91_000_000, "lng_micro": 0}),
    ):
        r = await http.get(f"/geo/places/{path}", params=params, headers=admin)
        assert r.status_code == 422, (path, params, r.text)
        error_shape(r)
    # equal distances: ordered by id
    a = await place(http, admin, "twin-a", LAT + 20_000, LNG + 40_000)
    b = await place(http, admin, "twin-b", LAT + 20_000, LNG + 40_000)
    twins = (await http.get("/geo/places/nearest", params={"lat_micro": LAT + 20_000, "lng_micro": LNG + 40_000, "n": 2}, headers=admin)).json()["items"]
    assert [t["id"] for t in twins] == sorted([a["id"], b["id"]]) and [t["distance_m"] for t in twins] == [0, 0]


# --- D13 geo: geofences ----------------------------------------------------------------------------------------


async def test_geofences_circle_polygon_and_contains(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    c = await circle(http, admin, "Yard", LAT, LNG, 500)
    assert c["shape"] == "circle" and c["radius_m"] == 500 and c["vertices"] is None and c["center"]["lat"] == "52.500000"
    square = [pt(LAT + 10_000, LNG + 10_000), pt(LAT + 10_000, LNG + 20_000), pt(LAT + 20_000, LNG + 20_000), pt(LAT + 20_000, LNG + 10_000)]
    r = await http.post("/geo/geofences", json={"name": "Zone", "shape": "polygon", "vertices": square}, headers=admin)
    assert r.status_code == 201, r.text
    z = r.json()
    assert z["shape"] == "polygon" and z["center"] is None and z["radius_m"] is None and len(z["vertices"]) == 4 and z["vertices"][0]["lat_micro"] == LAT + 10_000
    inside_circle = (await http.post("/geo/contains", json={"point": pt(LAT + 100, LNG)}, headers=people["driver"])).json()
    assert [f["id"] for f in inside_circle["items"]] == [c["id"]]
    inside_poly = (await http.post("/geo/contains", json={"point": pt(LAT + 15_000, LNG + 15_000)}, headers=admin)).json()
    assert [f["id"] for f in inside_poly["items"]] == [z["id"]]
    on_border = (await http.post("/geo/contains", json={"point": pt(LAT + 10_000, LNG + 15_000)}, headers=admin)).json()
    assert [f["id"] for f in on_border["items"]] == [z["id"]]  # the border counts as inside
    assert (await http.post("/geo/contains", json={"point": pt(LAT + 30_000, LNG)}, headers=admin)).json()["items"] == []
    assert (await http.post("/geo/contains", json={"point": {"lat": "52.5", "lng": "13.4"}}, headers=admin)).json()["items"][0]["id"] == c["id"]
    bowtie = [pt(LAT, LNG), pt(LAT + 10_000, LNG + 10_000), pt(LAT, LNG + 10_000), pt(LAT + 20_000, LNG)]
    bad = (
        ({"name": "x", "shape": "polygon", "vertices": bowtie}, "invalid_polygon"),
        ({"name": "x", "shape": "polygon", "vertices": [pt(LAT, LNG), pt(LAT, LNG + 5), pt(LAT, LNG + 10)]}, "invalid_polygon"),
        ({"name": "x", "shape": "polygon", "vertices": [pt(LAT, LNG), pt(LAT, LNG), pt(LAT + 5, LNG + 5)]}, "invalid_polygon"),
        ({"name": "x", "shape": "polygon", "vertices": [pt(LAT, LNG + i * 10) if i % 2 else pt(LAT + 10, LNG + i * 10) for i in range(13)]}, "invalid_polygon"),  # 13 > 12
        ({"name": "x", "shape": "polygon", "vertices": [pt(LAT, LNG), pt(LAT + 10, LNG)]}, "validation_error"),
        ({"name": "x", "shape": "polygon", "vertices": square, "radius_m": 5}, "validation_error"),
        ({"name": "x", "shape": "circle", "center": pt(), "radius_m": 0}, "validation_error"),
        ({"name": "x", "shape": "circle", "center": pt()}, "validation_error"),
        ({"name": "x", "shape": "circle", "center": pt(), "radius_m": 5_000_001}, "invalid_shape"),
        ({"name": "x", "shape": "circle", "center": pt(), "radius_m": 10.5}, "validation_error"),
        ({"name": "x", "shape": "square"}, "validation_error"),
        ({"name": "x", "shape": "circle", "center": {"lat_micro": 1}, "radius_m": 5}, "invalid_point"),
    )
    for body, code in bad:
        r = await http.post("/geo/geofences", json=body, headers=admin)
        assert r.status_code == 422 and error_shape(r) == code, (code, r.text)
    listed = (await http.get("/geo/geofences", headers=admin)).json()
    assert listed["total"] == 2 and [f["name"] for f in listed["items"]] == ["Yard", "Zone"]
    assert (await http.get(f"/geo/geofences/{z['id']}", headers=admin)).json()["id"] == z["id"]
    assert (await http.delete(f"/geo/geofences/{z['id']}", headers=admin)).status_code == 204
    assert (await http.get(f"/geo/geofences/{z['id']}", headers=admin)).status_code == 404
    assert (await http.delete(f"/geo/geofences/{z['id']}", headers=admin)).status_code == 404
    assert (await http.post("/geo/contains", json={"point": pt(LAT + 15_000, LNG + 15_000)}, headers=admin)).json()["items"] == []


async def test_places_and_geofences_can_be_edited(http, people) -> None:  # noqa: ANN001
    admin, disp, driver, other = people["admin"], people["disp"], people["driver"], people["b_admin"]
    p = await place(http, admin, "Depot", LAT, LNG, "depot")
    far = LAT + 3_000_000  # about 334 km away
    r = await http.put(f"/geo/places/{p['id']}", json={"name": "Depot 2", "kind": None, **pt(far, LNG + 5_000)}, headers=disp)
    assert r.status_code == 200, r.text
    moved = r.json()
    assert (moved["id"], moved["name"], moved["kind"], moved["lat_micro"], moved["lng_micro"], moved["created_at"]) == (p["id"], "Depot 2", None, far, LNG + 5_000, p["created_at"])
    assert (await http.put(f"/geo/places/{p['id']}", json={"name": "Dec", "lat": "10.5", "lng": "20.25"}, headers=admin)).json()["lat_micro"] == 10_500_000
    assert (await http.put(f"/geo/places/{p['id']}", json={"name": "Depot 2", "kind": "depot", **pt(far, LNG + 5_000)}, headers=admin)).status_code == 200
    assert (await http.get("/geo/places/within", params={**pt(), "radius_m": 1000}, headers=admin)).json()["items"] == []  # left the old spot
    assert [h["id"] for h in (await http.get("/geo/places/within", params={**pt(far, LNG + 5_000), "radius_m": 10}, headers=admin)).json()["items"]] == [p["id"]]
    nearest = (await http.get("/geo/places/nearest", params={**pt(far, LNG), "n": 1}, headers=driver)).json()["items"]
    assert nearest[0]["id"] == p["id"] and nearest[0]["kind"] == "depot"
    assert (await http.get(f"/geo/places/{p['id']}", headers=driver)).json()["lat_micro"] == far
    assert (await http.get("/geo/places", headers=admin)).json()["total"] == 1  # an edit never duplicates
    for body, code in (
        ({"name": "x"}, "invalid_point"),
        ({"name": "x", "lat_micro": 90_000_001, "lng_micro": 0}, "invalid_coordinates"),
        ({"name": "", **pt()}, "validation_error"),
        ({"name": "x\u0000y", **pt()}, "validation_error"),
        ({"name": "x", "kind": "k\u0000", **pt()}, "validation_error"),
        ({"name": "x", "colour": "red", **pt()}, "validation_error"),
    ):
        r = await http.put(f"/geo/places/{p['id']}", json=body, headers=admin)
        assert r.status_code == 422 and error_shape(r) == code, (body, r.text)
    assert (await http.get(f"/geo/places/{p['id']}", headers=admin)).json()["name"] == "Depot 2"  # refused edits change nothing
    assert (await http.put(f"/geo/places/{p['id']}", json={"name": "no", **pt()}, headers=driver)).status_code == 403
    assert (await http.put(f"/geo/places/{p['id']}", json={"name": "no", **pt()}, headers=people["nobody"])).status_code == 403
    assert (await http.put(f"/geo/places/{p['id']}", json={"name": "no", **pt()})).status_code in (401, 403)
    assert (await http.get(f"/geo/places/{p['id']}", headers=admin)).json()["name"] == "Depot 2"
    for target in (p["id"], "00000000-0000-0000-0000-000000000000"):
        r = await http.put(f"/geo/places/{target}", json={"name": "x", **pt()}, headers=other)
        assert r.status_code == 404 and error_shape(r) == "not_found", r.text
    assert (await http.put("/geo/places/not-a-uuid", json={"name": "x", **pt()}, headers=admin)).status_code == 422
    assert (await http.get(f"/geo/places/{p['id']}", headers=admin)).json()["name"] == "Depot 2"

    # geofence: circle -> polygon changes what contains says; the event history stays
    c = await circle(http, admin, "Yard", LAT, LNG, 500)
    assert (await http.post("/geo/evaluate", json={"subject_id": "van1", "point": pt()}, headers=admin)).json()["events"][0]["event"] == "enter"
    square = [pt(LAT + 10_000, LNG + 10_000), pt(LAT + 10_000, LNG + 20_000), pt(LAT + 20_000, LNG + 20_000), pt(LAT + 20_000, LNG + 10_000)]
    r = await http.put(f"/geo/geofences/{c['id']}", json={"name": "Zone", "shape": "polygon", "vertices": square}, headers=disp)
    assert r.status_code == 200, r.text
    z = r.json()
    assert (z["id"], z["name"], z["shape"], z["center"], z["radius_m"], z["created_at"]) == (c["id"], "Zone", "polygon", None, None, c["created_at"])
    assert len(z["vertices"]) == 4 and z["vertices"][0]["lat_micro"] == LAT + 10_000
    assert (await http.post("/geo/contains", json={"point": pt()}, headers=admin)).json()["items"] == []  # the old circle centre is out
    assert [f["id"] for f in (await http.post("/geo/contains", json={"point": pt(LAT + 15_000, LNG + 15_000)}, headers=admin)).json()["items"]] == [c["id"]]
    events = (await http.get("/geo/events", params={"geofence_id": c["id"]}, headers=admin)).json()
    assert events["total"] == 1 and events["items"][0]["event"] == "enter" and events["items"][0]["geofence_name"] == "Yard"  # history untouched
    out = (await http.post("/geo/evaluate", json={"subject_id": "van1", "point": pt(LAT + 15_000, LNG + 15_000)}, headers=admin)).json()
    assert out["inside"] == [c["id"]] and out["events"] == []  # still inside under the new shape: no exit, no second enter
    # polygon -> circle again, with a different box
    back = (await http.put(f"/geo/geofences/{c['id']}", json={"name": "Yard", "shape": "circle", "center": pt(LAT + 15_000, LNG + 15_000), "radius_m": 50}, headers=admin)).json()
    assert back["shape"] == "circle" and back["vertices"] is None and back["radius_m"] == 50 and back["center"]["lat_micro"] == LAT + 15_000
    assert [f["id"] for f in (await http.post("/geo/contains", json={"point": pt(LAT + 15_000, LNG + 15_030)}, headers=admin)).json()["items"]] == [c["id"]]
    assert (await http.post("/geo/contains", json={"point": pt(LAT + 16_000, LNG + 15_000)}, headers=admin)).json()["items"] == []
    assert (await http.get("/geo/geofences", headers=admin)).json()["total"] == 1
    bowtie = [pt(LAT, LNG), pt(LAT + 10_000, LNG + 10_000), pt(LAT, LNG + 10_000), pt(LAT + 20_000, LNG)]
    for body, code in (
        ({"name": "x", "shape": "polygon", "vertices": bowtie}, "invalid_polygon"),
        ({"name": "x", "shape": "polygon", "vertices": [pt(LAT + (10 if i % 2 else 0), LNG + i * 10) for i in range(13)]}, "invalid_polygon"),
        ({"name": "x", "shape": "circle", "center": pt(), "radius_m": 5_000_001}, "invalid_shape"),
        ({"name": "x", "shape": "circle", "center": pt(), "radius_m": 0}, "validation_error"),
        ({"name": "x", "shape": "circle", "center": pt(), "radius_m": 10.5}, "validation_error"),
        ({"name": "x", "shape": "polygon", "vertices": square, "radius_m": 5}, "validation_error"),
        ({"name": "x\u0000", "shape": "circle", "center": pt(), "radius_m": 5}, "validation_error"),
        ({"name": "x", "shape": "circle", "center": {"lat_micro": 1}, "radius_m": 5}, "invalid_point"),
    ):
        r = await http.put(f"/geo/geofences/{c['id']}", json=body, headers=admin)
        assert r.status_code == 422 and error_shape(r) == code, (code, r.text)
    assert (await http.get(f"/geo/geofences/{c['id']}", headers=admin)).json() == back  # refused edits change nothing
    body = {"name": "no", "shape": "circle", "center": pt(), "radius_m": 5}
    assert (await http.put(f"/geo/geofences/{c['id']}", json=body, headers=driver)).status_code == 403
    assert (await http.put(f"/geo/geofences/{c['id']}", json=body, headers=people["nobody"])).status_code == 403
    for target in (c["id"], "00000000-0000-0000-0000-000000000000"):
        r = await http.put(f"/geo/geofences/{target}", json=body, headers=other)
        assert r.status_code == 404 and error_shape(r) == "not_found", r.text
    assert (await http.get(f"/geo/geofences/{c['id']}", headers=admin)).json() == back
    assert (await http.get("/geo/geofences", headers=other)).json()["total"] == 0


async def test_the_geofence_limit_is_per_tenant(http, people) -> None:  # noqa: ANN001
    for i in range(20):
        await circle(http, people["admin"], f"F{i:02d}", LAT + i * 100_000, LNG, 100)
    r = await http.post("/geo/geofences", json={"name": "one too many", "shape": "circle", "center": pt(), "radius_m": 5}, headers=people["admin"])
    assert r.status_code == 422 and error_shape(r) == "limit_reached"
    await circle(http, people["b_admin"], "other tenant", LAT, LNG, 5)  # its own budget


async def test_evaluate_emits_enter_and_exit_once_even_in_parallel(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    yard = await circle(http, admin, "Yard", LAT, LNG, 500)
    other = await circle(http, admin, "Wide", LAT, LNG, 5_000)
    ev = lambda who, subject, lat, lng: http.post("/geo/evaluate", json={"subject_id": subject, "point": pt(lat, lng)}, headers=who)  # noqa: E731
    r = await ev(admin, "van1", LAT, LNG)
    body = r.json()
    assert r.status_code == 200 and sorted(body["inside"]) == sorted([yard["id"], other["id"]])
    assert sorted((e["event"], e["geofence_name"]) for e in body["events"]) == [("enter", "Wide"), ("enter", "Yard")]
    assert (await ev(admin, "van1", LAT + 100, LNG)).json()["events"] == []  # no change, no event
    moved = (await ev(admin, "van1", LAT + 10_000, LNG)).json()  # about 1.1 km: out of Yard, still in Wide
    assert moved["inside"] == [other["id"]] and [(e["event"], e["geofence_name"]) for e in moved["events"]] == [("exit", "Yard")]
    gone = (await ev(admin, "van1", LAT + 1_000_000, LNG)).json()
    assert gone["inside"] == [] and [(e["event"], e["geofence_name"]) for e in gone["events"]] == [("exit", "Wide")]
    events = (await http.get("/geo/events", params={"subject_id": "van1"}, headers=people["driver"])).json()
    assert events["total"] == 4 and [e["event"] for e in events["items"]].count("enter") == 2
    assert (await http.get("/geo/events", params={"geofence_id": yard["id"]}, headers=admin)).json()["total"] == 2
    # eight parallel evaluations of a fresh subject: the database decides, one enter per fence
    answers = await asyncio.gather(*[ev(admin, "van2", LAT, LNG) for _ in range(8)])
    assert all(a.status_code == 200 for a in answers), [a.text for a in answers]
    assert sum(len(a.json()["events"]) for a in answers) == 2
    assert (await http.get("/geo/events", params={"subject_id": "van2"}, headers=admin)).json()["total"] == 2
    leave = await asyncio.gather(*[ev(admin, "van2", LAT + 1_000_000, LNG) for _ in range(8)])
    assert sum(len(a.json()["events"]) for a in leave) == 2 and all(e["event"] == "exit" for a in leave for e in a.json()["events"])
    assert await scalar("select count(*) from geo_memberships where subject_id = 'van2'") == 0
    for body in ({"subject_id": "", "point": pt()}, {"subject_id": "x"}, {"subject_id": "x", "point": {"lat_micro": 1}}):
        r = await http.post("/geo/evaluate", json=body, headers=admin)
        assert r.status_code == 422, r.text
    # deleting a fence drops its memberships
    await ev(admin, "van3", LAT, LNG)
    assert (await http.delete(f"/geo/geofences/{yard['id']}", headers=admin)).status_code == 204
    assert await scalar("select count(*) from geo_memberships where geofence_id = :f", f=yard["id"]) == 0


async def test_distance_geocode_route_and_eta_are_deterministic_fakes(http, people) -> None:  # noqa: ANN001
    driver = people["driver"]
    r = await http.post("/geo/distance", json={"a": pt(0, 0), "b": pt(0, 1_000_000)}, headers=driver)
    assert r.status_code == 200 and r.json() == {"distance_m": 111_195}
    assert (await http.post("/geo/distance", json={"a": pt(0, 0), "b": {"lat": "0", "lng": "1"}}, headers=driver)).json() == {"distance_m": 111_195}
    assert (await http.post("/geo/distance", json={"a": pt(0, 179_999_000), "b": pt(0, -179_999_000)}, headers=driver)).json()["distance_m"] == 222
    assert (await http.post("/geo/distance", json={"a": pt(0, 0)}, headers=driver)).status_code == 422
    g1 = (await http.post("/geo/geocode", json={"address": "12 Main Street"}, headers=driver)).json()
    g2 = (await http.post("/geo/geocode", json={"address": "  12 main   STREET "}, headers=driver)).json()
    assert g1 == g2 and g1["provider"] == "fake" and set(g1) == {"lat_micro", "lng_micro", "lat", "lng", "provider"}
    assert g1 != (await http.post("/geo/geocode", json={"address": "13 Main Street"}, headers=driver)).json()
    for body in ({"address": ""}, {"address": "x" * 301}, {}):
        assert (await http.post("/geo/geocode", json=body, headers=driver)).status_code == 422
    route = (await http.post("/geo/route", json={"origin": pt(0, 0), "destination": pt(0, 1_000_000)}, headers=driver)).json()
    assert route == {"distance_m": 144_554, "duration_s": 10_400, "mode": "drive", "provider": "fake"}
    walk = (await http.post("/geo/route", json={"origin": pt(0, 0), "destination": pt(0, 1_000_000), "mode": "walk"}, headers=driver)).json()
    assert walk["mode"] == "walk" and walk["duration_s"] > route["duration_s"] and walk["distance_m"] == route["distance_m"]
    assert (await http.post("/geo/route", json={"origin": pt(0, 0), "destination": pt(0, 1), "mode": "boat"}, headers=driver)).status_code == 422
    depart = "2026-01-01T08:00:00+00:00"
    eta = (await http.post("/geo/eta", json={"origin": pt(0, 0), "destination": pt(0, 1_000_000), "depart_at": depart}, headers=driver)).json()
    assert eta["duration_s"] == 10_400 and eta["distance_m"] == 144_554 and eta["provider"] == "fake"
    assert datetime.fromisoformat(eta["arrives_at"]) == datetime(2026, 1, 1, 8, 0, tzinfo=UTC) + timedelta(seconds=10_400)
    assert (await http.post("/geo/eta", json={"origin": pt(0, 0), "destination": pt(0, 1)}, headers=driver)).status_code == 200


# --- D14 location ------------------------------------------------------------------------------------------------


async def report(http: AsyncClient, who: dict[str, str], subject: str, seq: int, lat: int = LAT, lng: int = LNG, **extra: object) -> Response:
    return await http.post("/location/positions", json={"subject_id": subject, "seq": seq, **pt(lat, lng), **extra}, headers=who)


async def test_a_stale_seq_never_overwrites_a_newer_position(http, people) -> None:  # noqa: ANN001
    driver = people["driver"]
    r = await report(http, driver, "van1", 5, LAT, LNG, subject_kind="van")
    assert r.status_code == 201 and r.json()["applied"] is True and r.json()["position"]["seq"] == 5 and r.json()["geofence_events"] == []
    assert r.json()["position"]["subject_kind"] == "van" and r.json()["position"]["lat"] == "52.500000"
    for seq in (5, 3, 0):
        stale = await report(http, driver, "van1", seq, LAT + 999, LNG + 999)
        assert stale.status_code == 200 and stale.json()["applied"] is False and stale.json()["reason"] == "stale"
        assert stale.json()["position"]["lat_micro"] == LAT and stale.json()["position"]["seq"] == 5 and stale.json()["geofence_events"] == []
    newer = await report(http, driver, "van1", 6, LAT + 1000, LNG)
    assert newer.status_code == 201 and newer.json()["position"]["lat_micro"] == LAT + 1000
    assert (await report(http, driver, "van1", 7, LAT + 2000, LNG, recorded_at=datetime.now(UTC).isoformat())).status_code == 201
    latest = (await http.get("/location/positions/van1", headers=driver)).json()
    assert (latest["seq"], latest["lat_micro"], latest["subject_kind"]) == (7, LAT + 2000, "van")  # kind kept when a report omits it
    assert (await http.get("/location/positions/ghost", headers=driver)).status_code == 404
    assert (await http.get("/location/positions/ghost/history", headers=driver)).status_code == 404
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = await report(http, driver, "van1", 8, recorded_at=future)
    assert r.status_code == 422 and error_shape(r) == "future_timestamp"
    for body in (
        {"subject_id": "van1", "seq": -1, **pt()},
        {"subject_id": "van1", "seq": 1.5, **pt()},
        {"subject_id": "van1", **pt()},
        {"subject_id": "", "seq": 1, **pt()},
        {"subject_id": "van1", "seq": 9},
        {"subject_id": "van1", "seq": 9, "lat_micro": 95_000_000, "lng_micro": 0},
    ):
        r = await http.post("/location/positions", json=body, headers=driver)
        assert r.status_code == 422, (body, r.text)
        error_shape(r)
    assert (await http.get("/location/positions/van1", headers=driver)).json()["seq"] == 7


async def test_eight_parallel_posts_with_different_seq_end_at_the_max(http, people) -> None:  # noqa: ANN001
    driver = people["driver"]
    answers = await asyncio.gather(*[report(http, driver, "van2", seq, LAT + seq * 10, LNG + seq) for seq in (4, 1, 8, 3, 7, 2, 6, 5)])
    assert all(a.status_code in (200, 201) for a in answers), [a.text for a in answers]
    assert any(a.status_code == 201 for a in answers)
    for a in answers:
        assert a.json()["applied"] == (a.status_code == 201)
    final = (await http.get("/location/positions/van2", headers=driver)).json()
    assert (final["seq"], final["lat_micro"], final["lng_micro"]) == (8, LAT + 80, LNG + 8)
    assert await scalar("select count(*) from location_positions where subject_id = 'van2'") == 1
    history = (await http.get("/location/positions/van2/history", headers=driver)).json()
    seqs = [h["seq"] for h in history["items"]]
    assert seqs == sorted(seqs, reverse=True) and seqs[0] == 8 and len(seqs) <= 5 and history["retention_cap"] == 5
    assert all(h["lat_micro"] == LAT + h["seq"] * 10 for h in history["items"])
    # the same seq in parallel: exactly one applies
    same = await asyncio.gather(*[report(http, driver, "van3", 1, LAT, LNG + i) for i in range(8)])
    assert sorted(a.status_code for a in same) == [200] * 7 + [201]


async def test_history_is_capped_per_subject(http, people) -> None:  # noqa: ANN001
    driver = people["driver"]
    for seq in range(1, 13):
        assert (await report(http, driver, "van4", seq, LAT + seq, LNG)).status_code == 201
    history = (await http.get("/location/positions/van4/history", headers=driver)).json()
    assert [h["seq"] for h in history["items"]] == [12, 11, 10, 9, 8] and history["retention_cap"] == 5
    assert [h["seq"] for h in (await http.get("/location/positions/van4/history", params={"limit": 2}, headers=driver)).json()["items"]] == [12, 11]
    assert await scalar("select count(*) from location_history where subject_id = 'van4'") == 5
    assert (await http.get("/location/positions/van4/history", params={"limit": 501}, headers=driver)).status_code == 422
    await report(http, driver, "van5", 1)
    assert await scalar("select count(*) from location_history where subject_id = 'van5'") == 1  # another subject is untouched


async def test_box_query_including_across_the_antimeridian(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    await report(http, admin, "east", 1, 10_000_000, 179_900_000, subject_kind="boat")
    await report(http, admin, "west", 1, 10_000_000, -179_900_000, subject_kind="boat")
    await report(http, admin, "mid", 1, 10_000_000, 0, subject_kind="van")
    await report(http, admin, "south", 1, -40_000_000, 179_900_000, subject_kind="boat")
    across = {"min_lat_micro": 0, "max_lat_micro": 20_000_000, "min_lng_micro": 179_000_000, "max_lng_micro": -179_000_000}
    found = (await http.get("/location/positions", params=across, headers=admin)).json()
    assert sorted(i["subject_id"] for i in found["items"]) == ["east", "west"] and found["truncated"] is False
    plain = {"min_lat_micro": 0, "max_lat_micro": 20_000_000, "min_lng_micro": -180_000_000, "max_lng_micro": 180_000_000}
    assert sorted(i["subject_id"] for i in (await http.get("/location/positions", params=plain, headers=admin)).json()["items"]) == ["east", "mid", "west"]
    kind = (await http.get("/location/positions", params={**plain, "subject_kind": "van"}, headers=admin)).json()
    assert [i["subject_id"] for i in kind["items"]] == ["mid"]
    one = (await http.get("/location/positions", params={**across, "limit": 1}, headers=admin)).json()
    assert len(one["items"]) == 1 and one["truncated"] is True
    for params in (
        {**across, "min_lat_micro": 30_000_000},
        {**across, "min_lat_micro": -91_000_000},
        {**across, "max_lng_micro": 181_000_000},
        {"min_lat_micro": 0},
        {**across, "limit": 501},
    ):
        r = await http.get("/location/positions", params=params, headers=admin)
        assert r.status_code == 422, (params, r.text)
        error_shape(r)
    assert (await http.get("/location/positions", params={**across, "min_lat_micro": 30_000_000}, headers=admin)).json()["code"] == "invalid_box"


async def test_positions_raise_geofence_events_when_geo_is_declared(http, people) -> None:  # noqa: ANN001
    yard = await circle(http, people["admin"], "Yard", LAT, LNG, 500)
    first = (await report(http, people["driver"], "van6", 1, LAT, LNG)).json()
    assert [(e["event"], e["geofence_id"], e["geofence_name"], e["subject_id"]) for e in first["geofence_events"]] == [("enter", yard["id"], "Yard", "van6")]
    assert (await report(http, people["driver"], "van6", 2, LAT + 100, LNG)).json()["geofence_events"] == []
    out = (await report(http, people["driver"], "van6", 3, LAT + 50_000, LNG)).json()
    assert [e["event"] for e in out["geofence_events"]] == ["exit"]
    stale = (await report(http, people["driver"], "van6", 2, LAT, LNG)).json()  # stale: no evaluation
    assert stale["applied"] is False and stale["geofence_events"] == []
    assert (await http.get("/geo/events", params={"subject_id": "van6"}, headers=people["admin"])).json()["total"] == 2


# --- D15 matching -----------------------------------------------------------------------------------------------


def cand(cid: str, lat: int | None = None, lng: int = LNG, load: int = 0, rating: int = 0) -> dict:
    body: dict = {"id": cid, "load": load, "rating_milli": rating}
    if lat is not None:
        body.update(pt(lat, lng))
    return body


def pool() -> list[dict]:
    return [
        cand("A", LAT, load=0, rating=4500),
        cand("B", LAT + 40_000, load=3, rating=1000),  # about 4.4 km
        cand("C", LAT + 400_000, load=0, rating=5000),  # about 44 km: too far
        cand("D", LAT, load=5, rating=5000),  # at the load limit: overloaded
    ]


async def assign(http: AsyncClient, who: dict[str, str], ref: str, candidates: list[dict] | None = None, lat: int = LAT) -> Response:
    return await http.post("/matching/assignments", json={"request_ref": ref, "point": pt(lat, LNG), "candidates": candidates or pool()}, headers=who)


async def test_rank_scores_are_integers_from_the_declared_weights(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    r = await http.post("/matching/rank", json={"point": pt(), "candidates": pool()}, headers=disp)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["candidate_id"] for i in body["items"]] == ["A", "B"]
    a, b = body["items"]
    assert (a["distance_m"], a["parts"], a["score"]) == (0, {"distance": 1000, "load": 1000, "rating": 900}, 600 * 1000 + 300 * 1000 + 100 * 900)
    d = b["distance_m"]
    assert 4_000 < d < 5_000
    parts = {"distance": 1000 - 1000 * d // 20_000, "load": 1000 - 1000 * 3 // 5, "rating": 1000 // 5}
    assert b["parts"] == parts and b["score"] == 600 * parts["distance"] + 300 * parts["load"] + 100 * parts["rating"]
    assert body["excluded"] == [{"candidate_id": "C", "reason": "too_far"}, {"candidate_id": "D", "reason": "overloaded"}]
    assert await scalar("select count(*) from match_assignments") == 0  # nothing stored
    # ties: score, then distance, then id
    tie = (await http.post("/matching/rank", json={"point": pt(), "candidates": [cand("z", LAT), cand("m", LAT), cand("n", LAT)]}, headers=disp)).json()
    assert [i["candidate_id"] for i in tie["items"]] == ["m", "n", "z"]
    for body_ in (
        {"point": pt(), "candidates": []},
        {"point": pt(), "candidates": [cand("x", LAT), cand("x", LAT)]},
        {"point": pt(), "candidates": [{"id": "x", "load": -1, "lat_micro": 1, "lng_micro": 1}]},
        {"point": pt(), "candidates": [{"id": "x", "rating_milli": 5001, "lat_micro": 1, "lng_micro": 1}]},
        {"point": pt(), "candidates": [{"id": "x", "load": 1.5, "lat_micro": 1, "lng_micro": 1}]},
        {"point": pt(), "candidates": [{"id": "x", "lat_micro": 1}]},
        {"point": pt(), "candidates": [cand(f"c{i}", LAT) for i in range(201)]},
        {"candidates": [cand("x", LAT)]},
    ):
        r = await http.post("/matching/rank", json=body_, headers=disp)
        assert r.status_code == 422, (body_, r.text)
        error_shape(r)


async def test_candidates_without_coordinates_use_their_latest_position(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    ask = {"point": pt(), "candidates": [cand("ghost")]}
    r = await http.post("/matching/rank", json=ask, headers=disp)
    assert r.status_code == 422 and error_shape(r) == "candidate_without_location"
    assert (await report(http, people["driver"], "ghost", 1, LAT + 1000, LNG)).status_code == 201
    ok = (await http.post("/matching/rank", json=ask, headers=disp)).json()
    assert ok["items"][0]["candidate_id"] == "ghost" and ok["items"][0]["distance_m"] == 111
    r = await assign(http, disp, "loc-1", [cand("ghost"), cand("nobody-knows")])
    assert r.status_code == 422 and error_shape(r) == "candidate_without_location"
    assert (await assign(http, disp, "loc-1", [cand("ghost")])).status_code == 201


async def test_assignment_lifecycle_offered_accepted_rejected_expired(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    r = await assign(http, disp, "job-1")
    assert r.status_code == 201, r.text
    first = r.json()
    assert (first["status"], first["candidate_id"], first["request_ref"], first["decided_at"], first["decided_by"]) == ("offered", "A", "job-1", None, None)
    assert first["score"] == 990_000 and first["distance_m"] == 0
    ttl = datetime.fromisoformat(first["expires_at"]) - datetime.fromisoformat(first["offered_at"])
    assert ttl == timedelta(seconds=300)
    again = await assign(http, disp, "job-1")
    assert again.status_code == 409 and error_shape(again) == "already_assigned"
    got = await http.get(f"/matching/assignments/{first['id']}", headers=disp)
    assert got.status_code == 200 and got.json()["id"] == first["id"]
    accepted = await http.post(f"/matching/assignments/{first['id']}/accept", headers=disp)
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted" and accepted.json()["decided_by"] is not None
    for verb in ("accept", "reject", "expire"):
        r = await http.post(f"/matching/assignments/{first['id']}/{verb}", headers=disp)
        assert r.status_code == 409 and error_shape(r) == "invalid_state", (verb, r.text)
    assert (await assign(http, disp, "job-1")).status_code == 409  # an accepted assignment still holds the request
    # reject: the request may be assigned again, the rejecting candidate is skipped for it
    second = (await assign(http, disp, "job-2")).json()
    assert second["candidate_id"] == "A"
    rejected = await http.post(f"/matching/assignments/{second['id']}/reject", headers=disp)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    retry = await assign(http, disp, "job-2")
    assert retry.status_code == 201 and retry.json()["candidate_id"] == "B"
    # expire by hand: skipped as well; when everyone declined there is no candidate left
    r = await http.post(f"/matching/assignments/{retry.json()['id']}/expire", headers=disp)
    assert r.status_code == 200 and r.json()["status"] == "expired"
    none = await assign(http, disp, "job-2")
    assert none.status_code == 422 and error_shape(none) == "no_candidates"
    # a request with nobody eligible
    r = await assign(http, disp, "job-3", [cand("far", LAT + 4_000_000)])
    assert r.status_code == 422 and error_shape(r) == "no_candidates"
    listed = (await http.get("/matching/assignments", headers=disp)).json()
    assert listed["total"] == 3 and listed["items"][0]["request_ref"] == "job-2"
    assert (await http.get("/matching/assignments", params={"status": "accepted"}, headers=disp)).json()["total"] == 1
    assert (await http.get("/matching/assignments", params={"request_ref": "job-2"}, headers=disp)).json()["total"] == 2
    assert (await http.get("/matching/assignments", params={"candidate_id": "B"}, headers=disp)).json()["total"] == 1
    assert (await http.get("/matching/assignments", params={"status": "weird"}, headers=disp)).status_code == 422
    for verb in ("accept", "reject", "expire"):
        r = await http.post(f"/matching/assignments/00000000-0000-0000-0000-000000000000/{verb}", headers=disp)
        assert r.status_code == 404 and error_shape(r) == "not_found"


async def test_an_offer_past_its_expiry_cannot_be_accepted_and_is_swept(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    old = (await assign(http, disp, "late-1")).json()
    await execute("update match_assignments set expires_at = now() - interval '1 minute' where id = :i", i=old["id"])
    r = await http.post(f"/matching/assignments/{old['id']}/accept", headers=disp)
    assert r.status_code == 409 and error_shape(r) == "expired"
    assert (await http.get(f"/matching/assignments/{old['id']}", headers=disp)).json()["status"] == "expired"
    # a due offer is replaced by a new assign for the same request (A declined by silence is skipped)
    due = (await assign(http, disp, "late-2")).json()
    await execute("update match_assignments set expires_at = now() - interval '1 minute' where id = :i", i=due["id"])
    renewed = await assign(http, disp, "late-2")
    assert renewed.status_code == 201 and renewed.json()["candidate_id"] == "B"
    # the sweep: two due offers
    for ref in ("late-3", "late-4"):
        row = (await assign(http, disp, ref)).json()
        await execute("update match_assignments set expires_at = now() - interval '1 minute' where id = :i", i=row["id"])
    swept = await http.post("/matching/expire-due", headers=disp)
    assert swept.status_code == 200 and swept.json() == {"expired": 2}
    assert (await http.post("/matching/expire-due", headers=disp)).json() == {"expired": 0}
    assert (await http.get("/matching/assignments", params={"status": "offered"}, headers=disp)).json()["total"] == 1  # late-2 (B)


async def test_eight_parallel_assigns_for_one_request_give_one_201_and_seven_409(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    answers = await asyncio.gather(*[assign(http, disp, "race-1") for _ in range(8)])
    assert sorted(a.status_code for a in answers) == [201] + [409] * 7, [a.text for a in answers]
    assert [error_shape(a) for a in answers if a.status_code == 409] == ["already_assigned"] * 7
    assert await scalar("select count(*) from match_assignments where request_ref = 'race-1' and status in ('offered', 'accepted')") == 1
    # parallel assigns for different requests all succeed
    many = await asyncio.gather(*[assign(http, disp, f"race-many-{i}") for i in range(8)])
    assert [a.status_code for a in many] == [201] * 8
    # parallel accepts of one offer: one winner
    offer = (await assign(http, disp, "race-2")).json()
    decided = await asyncio.gather(*[http.post(f"/matching/assignments/{offer['id']}/{verb}", headers=disp) for verb in ("accept", "reject", "expire", "accept")])
    assert sorted(d.status_code for d in decided) == [200, 409, 409, 409], [d.text for d in decided]
    final = (await http.get(f"/matching/assignments/{offer['id']}", headers=disp)).json()["status"]
    assert final in ("accepted", "rejected", "expired")


async def test_batch_solves_exactly_and_commits_on_request(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    cands = [cand("A", LAT), cand("B", LAT + 40_000), cand("C", LAT + 80_000)]
    reqs = [{"request_ref": "b1", "point": pt(LAT, LNG)}, {"request_ref": "b2", "point": pt(LAT + 40_000, LNG)}, {"request_ref": "b3", "point": pt(LAT + 80_000, LNG)}, {"request_ref": "b4", "point": pt(LAT + 5_000_000, LNG)}]
    r = await http.post("/matching/batch", json={"requests": reqs, "candidates": cands}, headers=disp)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["solver"] == "optimal" and out["unassigned"] == ["b4"] and out["assignments"] == [] and out["skipped"] == []
    assert {(p["request_ref"], p["candidate_id"]) for p in out["pairs"]} == {("b1", "A"), ("b2", "B"), ("b3", "C")}
    assert len({p["candidate_id"] for p in out["pairs"]}) == 3 and out["total_score"] == sum(p["score"] for p in out["pairs"])
    assert await scalar("select count(*) from match_assignments") == 0
    r = await http.post("/matching/batch", json={"requests": reqs, "candidates": cands, "commit": True}, headers=disp)
    committed = r.json()
    assert r.status_code == 200 and len(committed["assignments"]) == 3 and {a["status"] for a in committed["assignments"]} == {"offered"}
    assert committed["pairs"] == out["pairs"]
    # the same batch again: the requests are already active, so they are skipped, not duplicated
    r = await http.post("/matching/batch", json={"requests": reqs, "candidates": cands, "commit": True}, headers=disp)
    again = r.json()
    assert r.status_code == 200 and again["pairs"] == [] and again["assignments"] == [] and again["skipped"] == ["b1", "b2", "b3"] and again["unassigned"] == ["b4"]
    assert await scalar("select count(*) from match_assignments") == 3
    # each candidate takes at most one request: 2 requests at the same spot, 1 candidate
    r = await http.post("/matching/batch", json={"requests": [{"request_ref": "x1", "point": pt()}, {"request_ref": "x2", "point": pt()}], "candidates": [cand("only", LAT)]}, headers=disp)
    assert len(r.json()["pairs"]) == 1 and len(r.json()["unassigned"]) == 1
    # more than the exact solver takes: greedy, still one request per candidate
    big = [{"request_ref": f"g{i:02d}", "point": pt(LAT + i * 1000, LNG)} for i in range(10)]
    r = await http.post("/matching/batch", json={"requests": big, "candidates": [cand(f"k{i:02d}", LAT + i * 1000) for i in range(10)]}, headers=disp)
    assert r.json()["solver"] == "greedy" and len(r.json()["pairs"]) == 10 and len({p["candidate_id"] for p in r.json()["pairs"]}) == 10
    for body in (
        {"requests": [], "candidates": cands},
        {"requests": reqs[:1] * 2, "candidates": cands},
        {"requests": [{"request_ref": f"r{i}", "point": pt()} for i in range(101)], "candidates": cands},
        {"requests": reqs, "candidates": []},
        {"requests": reqs, "candidates": cands, "commit": [1]},
    ):
        r = await http.post("/matching/batch", json=body, headers=disp)
        assert r.status_code == 422, (list(body), r.text)
        error_shape(r)


# --- D16 prediction ---------------------------------------------------------------------------------------------


async def predict(http: AsyncClient, who: dict[str, str], ref: str, kind: str = "eta", **features: object) -> Response:
    return await http.post("/prediction/predict", json={"kind": kind, "subject_ref": ref, "features": features or {"stops": 3, "zone": "north", "rush": True}}, headers=who)


async def test_predictions_are_deterministic_integer_records(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    r = await predict(http, disp, "job-1")
    assert r.status_code == 201, r.text
    rec = r.json()
    assert (rec["kind"], rec["subject_ref"], rec["model_id"], rec["unit"], rec["actual"], rec["actual_at"]) == ("eta", "job-1", "fake-linear-v1", "minutes", None, None)
    assert all(type(rec[k]) is int for k in ("value", "low", "high")) and rec["low"] <= rec["value"] <= rec["high"]
    assert rec["features"] == {"stops": 3, "zone": "north", "rush": True} and 3 + 5 + 1 <= rec["value"] < 9 + 100
    again = (await predict(http, disp, "job-1")).json()
    assert (again["value"], again["low"], again["high"], again["model_id"]) == (rec["value"], rec["low"], rec["high"], rec["model_id"]) and again["id"] != rec["id"]
    for body in (
        {"kind": "", "subject_ref": "x", "features": {}},
        {"kind": "bad kind!", "subject_ref": "x", "features": {}},
        {"kind": "eta", "subject_ref": "", "features": {}},
        {"kind": "eta", "subject_ref": "x", "features": {"a": 1.5}},
        {"kind": "eta", "subject_ref": "x", "features": {"a": None}},
        {"kind": "eta", "subject_ref": "x", "features": {"a": [1]}},
        {"kind": "eta", "subject_ref": "x", "features": {"a": 2**60}},
        {"kind": "eta", "subject_ref": "x", "features": {"": 1}},
        {"kind": "eta", "subject_ref": "x", "features": {f"f{i}": i for i in range(51)}},
        {"kind": "eta", "subject_ref": "x", "features": {}, "model": "gpt"},
    ):
        r = await http.post("/prediction/predict", json=body, headers=disp)
        assert r.status_code == 422, (body, r.text)
        error_shape(r)
    got = await http.get(f"/prediction/records/{rec['id']}", headers=disp)
    assert got.status_code == 200 and got.json() == rec
    listed = (await http.get("/prediction/records", headers=disp)).json()
    assert listed["total"] == 2 and listed["items"][0]["subject_ref"] == "job-1"
    assert (await http.get("/prediction/records", params={"subject_ref": "job-1"}, headers=disp)).json()["total"] == 2
    assert (await http.get("/prediction/records", params={"kind": "nope"}, headers=disp)).json()["total"] == 0
    assert (await http.get("/prediction/records", params={"has_actual": "true"}, headers=disp)).json()["total"] == 0


async def test_actuals_are_recorded_once_and_idempotently(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    rec = (await predict(http, disp, "job-1")).json()
    first = await http.post(f"/prediction/records/{rec['id']}/actual", json={"actual": rec["value"] + 7}, headers=disp)
    assert first.status_code == 200 and first.json()["actual"] == rec["value"] + 7 and first.json()["actual_at"] is not None
    stamp = first.json()["actual_at"]
    same = await http.post(f"/prediction/records/{rec['id']}/actual", json={"actual": rec["value"] + 7}, headers=disp)
    assert same.status_code == 200 and same.json()["actual_at"] == stamp
    different = await http.post(f"/prediction/records/{rec['id']}/actual", json={"actual": rec["value"] + 8}, headers=disp)
    assert different.status_code == 409 and error_shape(different) == "actual_already_recorded"
    assert (await http.get(f"/prediction/records/{rec['id']}", headers=disp)).json()["actual"] == rec["value"] + 7
    missing = await http.post("/prediction/records/00000000-0000-0000-0000-000000000000/actual", json={"actual": 1}, headers=disp)
    assert missing.status_code == 404 and error_shape(missing) == "not_found"
    for body in ({"actual": 1.5}, {"actual": "7"}, {}, {"actual": 2**60}, {"actual": 1, "extra": 1}):
        r = await http.post(f"/prediction/records/{rec['id']}/actual", json=body, headers=disp)
        assert r.status_code == 422, (body, r.text)
    assert (await http.get("/prediction/records", params={"has_actual": "true"}, headers=disp)).json()["total"] == 1
    # parallel: two different values, one wins; everybody who sent the winner's value gets 200, the rest 409
    other = (await predict(http, disp, "job-9")).json()
    answers = await asyncio.gather(*[http.post(f"/prediction/records/{other['id']}/actual", json={"actual": 100 + i % 2}, headers=disp) for i in range(8)])
    winner = (await http.get(f"/prediction/records/{other['id']}", headers=disp)).json()["actual"]
    assert winner in (100, 101)
    for i, a in enumerate(answers):
        assert a.status_code == (200 if 100 + i % 2 == winner else 409), (i, a.text)


async def test_stats_use_integer_mae_and_interval_coverage(http, people) -> None:  # noqa: ANN001
    disp = people["disp"]
    empty = (await http.get("/prediction/stats", headers=disp)).json()
    assert empty == {"logged": 0, "with_actual": 0, "mae_milli": None, "abs_error_sum": 0, "covered": 0, "coverage_bp": None}
    recs = [(await predict(http, disp, f"s{i}", kind="stat", n=i)).json() for i in range(4)]
    for rec, delta in zip(recs[:3], (0, 1000, -1000), strict=True):
        assert (await http.post(f"/prediction/records/{rec['id']}/actual", json={"actual": rec["value"] + delta}, headers=disp)).status_code == 200
    await predict(http, disp, "elsewhere", kind="other")
    stats = (await http.get("/prediction/stats", params={"kind": "stat"}, headers=disp)).json()
    assert stats == {"logged": 4, "with_actual": 3, "mae_milli": 666_667, "abs_error_sum": 2000, "covered": 1, "coverage_bp": 3333}
    assert (await http.get("/prediction/stats", params={"kind": "stat", "model_id": "fake-linear-v1"}, headers=disp)).json() == stats
    assert (await http.get("/prediction/stats", params={"kind": "stat", "model_id": "other-model"}, headers=disp)).json()["logged"] == 0
    assert (await http.get("/prediction/stats", headers=disp)).json()["logged"] == 5
    # MAE x 1000 rounds half to even: errors 0 and 1 -> 500 exactly; errors 1, 1, 1, 0 -> 750; errors 0, 0, 1 / 8 style ties
    pair = [(await predict(http, disp, f"p{i}", kind="tie", n=i)).json() for i in range(2)]
    for rec, delta in zip(pair, (0, 1), strict=True):
        await http.post(f"/prediction/records/{rec['id']}/actual", json={"actual": rec["value"] + delta}, headers=disp)
    tie = (await http.get("/prediction/stats", params={"kind": "tie"}, headers=disp)).json()
    assert tie["mae_milli"] == 500 and tie["abs_error_sum"] == 1 and tie["coverage_bp"] == 10_000


# --- tenants and roles -------------------------------------------------------------------------------------------


async def test_another_tenant_sees_nothing_and_gets_404(http, people) -> None:  # noqa: ANN001
    admin, other = people["admin"], people["b_admin"]
    p = await place(http, admin, "mine", LAT, LNG)
    fence = await circle(http, admin, "Yard", LAT, LNG, 500)
    await report(http, admin, "van1", 1, LAT, LNG)
    a = (await assign(http, admin, "job-1")).json()
    rec = (await predict(http, admin, "job-1")).json()
    for method, path in (
        ("get", f"/geo/places/{p['id']}"),
        ("delete", f"/geo/places/{p['id']}"),
        ("get", f"/geo/geofences/{fence['id']}"),
        ("delete", f"/geo/geofences/{fence['id']}"),
        ("get", "/location/positions/van1"),
        ("get", "/location/positions/van1/history"),
        ("get", f"/matching/assignments/{a['id']}"),
        ("post", f"/matching/assignments/{a['id']}/accept"),
        ("post", f"/matching/assignments/{a['id']}/reject"),
        ("post", f"/matching/assignments/{a['id']}/expire"),
        ("get", f"/prediction/records/{rec['id']}"),
    ):
        r = await getattr(http, method)(path, headers=other)
        assert r.status_code == 404 and error_shape(r) == "not_found", (method, path, r.text)
    r = await http.post(f"/prediction/records/{rec['id']}/actual", json={"actual": 1}, headers=other)
    assert r.status_code == 404
    # nothing leaks into lists and queries
    assert (await http.get("/geo/places", headers=other)).json()["total"] == 0
    assert (await http.get("/geo/places/within", params={**pt(), "radius_m": 1000}, headers=other)).json()["items"] == []
    assert (await http.get("/geo/places/nearest", params=pt(), headers=other)).json()["items"] == []
    assert (await http.post("/geo/contains", json={"point": pt()}, headers=other)).json()["items"] == []
    assert (await http.get("/geo/geofences", headers=other)).json()["total"] == 0
    assert (await http.get("/geo/events", headers=other)).json()["total"] == 0
    box = {"min_lat_micro": 0, "max_lat_micro": 90_000_000, "min_lng_micro": 0, "max_lng_micro": 90_000_000}
    assert (await http.get("/location/positions", params=box, headers=other)).json()["items"] == []
    assert (await http.get("/matching/assignments", headers=other)).json()["total"] == 0
    assert (await http.get("/prediction/records", headers=other)).json()["total"] == 0
    assert (await http.get("/prediction/stats", headers=other)).json()["logged"] == 0
    # the same ids in another tenant are independent: its own van1 and its own job-1
    assert (await report(http, other, "van1", 1, 1000, 1000)).status_code == 201
    assert (await http.get("/location/positions/van1", headers=admin)).json()["lat_micro"] == LAT
    assert (await assign(http, other, "job-1", [cand("A", LAT)])).status_code == 201
    # another tenant's position is not a candidate's location
    r = await http.post("/matching/rank", json={"point": pt(), "candidates": [cand("van1")]}, headers=people["disp"])
    assert r.status_code == 200 and r.json()["items"][0]["distance_m"] == 0
    # an evaluation in another tenant does not see this tenant's fences
    assert (await http.post("/geo/evaluate", json={"subject_id": "v", "point": pt()}, headers=other)).json() == {"inside": [], "events": []}


async def test_roles_are_enforced(http, people) -> None:  # noqa: ANN001
    nobody, driver, disp = people["nobody"], people["driver"], people["disp"]
    rank = {"point": pt(), "candidates": pool()}
    calls = [
        ("get", "/geo/places", None),
        ("post", "/geo/places", {"name": "x", **pt()}),
        ("get", "/geo/places/within", None),
        ("post", "/geo/geofences", {"name": "x", "shape": "circle", "center": pt(), "radius_m": 5}),
        ("post", "/geo/contains", {"point": pt()}),
        ("post", "/geo/distance", {"a": pt(), "b": pt()}),
        ("post", "/geo/evaluate", {"subject_id": "x", "point": pt()}),
        ("get", "/geo/events", None),
        ("post", "/geo/geocode", {"address": "x"}),
        ("post", "/location/positions", {"subject_id": "x", "seq": 1, **pt()}),
        ("get", "/location/positions/x", None),
        ("post", "/matching/rank", rank),
        ("post", "/matching/assignments", {"request_ref": "r", **rank}),
        ("post", "/matching/expire-due", None),
        ("post", "/prediction/predict", {"kind": "eta", "subject_ref": "x", "features": {}}),
        ("get", "/prediction/stats", None),
        ("get", "/prediction/records", None),
    ]
    for method, path, body in calls:
        kwargs = {"json": body} if body is not None else {}
        r = await getattr(http, method)(path, headers=nobody, **kwargs)
        assert r.status_code == 403 and error_shape(r) == "forbidden", (method, path, r.text)
        r = await getattr(http, method)(path, **kwargs)
        assert r.status_code in (401, 403), (method, path, r.status_code)
    # the remaining routes (by id, adapters, box, actions) refuse a user without a role too
    ghost = "00000000-0000-0000-0000-000000000000"
    more = [
        ("get", f"/geo/places/{ghost}", None), ("put", f"/geo/places/{ghost}", {"name": "x", **pt()}), ("delete", f"/geo/places/{ghost}", None),
        ("get", "/geo/places/nearest", None), ("get", f"/geo/geofences/{ghost}", None), ("get", "/geo/geofences", None),
        ("put", f"/geo/geofences/{ghost}", {"name": "x", "shape": "circle", "center": pt(), "radius_m": 5}), ("delete", f"/geo/geofences/{ghost}", None),
        ("post", "/geo/route", {"origin": pt(), "destination": pt()}), ("post", "/geo/eta", {"origin": pt(), "destination": pt()}),
        ("get", "/location/positions", None), ("get", "/location/positions/x/history", None),
        ("post", "/matching/batch", {"requests": [{"request_ref": "r", "point": pt()}], "candidates": pool()}), ("get", "/matching/assignments", None), ("get", f"/matching/assignments/{ghost}", None),
        ("post", f"/matching/assignments/{ghost}/accept", None), ("post", f"/matching/assignments/{ghost}/reject", None), ("post", f"/matching/assignments/{ghost}/expire", None),
        ("get", f"/prediction/records/{ghost}", None), ("post", f"/prediction/records/{ghost}/actual", {"actual": 1}),
    ]
    for method, path, body in more:
        kwargs = {"json": body} if body is not None else {}
        r = await getattr(http, method)(path, headers=nobody, **kwargs)
        assert r.status_code == 403 and error_shape(r) == "forbidden", (method, path, r.status_code, r.text)
    # a driver reads geo and writes positions, but nothing else
    assert (await http.get("/geo/places", headers=driver)).status_code == 200
    assert (await http.post("/geo/places", json={"name": "x", **pt()}, headers=driver)).status_code == 403
    assert (await http.post("/geo/evaluate", json={"subject_id": "x", "point": pt()}, headers=driver)).status_code == 403
    assert (await report(http, driver, "van1", 1)).status_code == 201
    for method, path, body in calls:
        if path.startswith(("/matching", "/prediction")):
            kwargs = {"json": body} if body is not None else {}
            assert (await getattr(http, method)(path, headers=driver, **kwargs)).status_code == 403, path
    # a dispatcher writes geo and matches
    assert (await http.post("/geo/places", json={"name": "x", **pt()}, headers=disp)).status_code == 201
    assert (await http.post("/matching/rank", json=rank, headers=disp)).status_code == 200
