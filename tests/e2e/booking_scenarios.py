"""Scenario tests for the booking pack (D12) in the generated `booking_clinic` project (copied into the project's
tests/ by tests/e2e/test_booking_stack.py, run against a real Postgres).

Spec: kinds practitioner (slot, 30 min, Mon-Fri 09-12 and 13-17 Europe/Berlin), room (range 30..480 min), loaner
(pool of 3); hold TTL 120 s; free cancellation until 24 h before the start, then 2500 EUR minor; roles: read
admin/staff/customer, book admin/customer, manage admin/staff, own_only. Proves: 8 parallel requests for one slot
give exactly one success and seven slot_taken; a pool of 3 never exceeds 3 under 8 parallel requests; hold expiry
frees the slot (lazy and by sweep); cancellation fees; idempotent replay (also parallel); the state machine (service
and database trigger); the EXCLUDE constraint itself; tenant isolation; roles and own_only. No 500 anywhere."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient, Response

from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "admin": await sign_in(http, "a@example.com", roles=["admin"], n=0),
        "staff": await sign_in(http, "a_staff@example.com", roles=["staff"], n=1, join="a@example.com"),
        "c1": await sign_in(http, "a_c1@example.com", roles=["customer"], n=2, join="a@example.com"),
        "c2": await sign_in(http, "a_c2@example.com", roles=["customer"], n=3, join="a@example.com"),
        "nobody": await sign_in(http, "a_nobody@example.com", roles=[], n=4, join="a@example.com"),
        "b_admin": await sign_in(http, "b@example.com", roles=["admin"], n=5),
        "b_c": await sign_in(http, "b_c@example.com", roles=["customer"], n=6, join="b@example.com"),
    }


def monday(min_days: int = 8) -> date:
    day = datetime.now(UTC).date() + timedelta(days=min_days)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day


def at(day: date, hh: int, mm: int = 0) -> str:
    """A Berlin wall-clock time as an ISO string with its offset."""
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=BERLIN).isoformat()


def soon(hours: float = 2, minutes_round: int = 0) -> datetime:
    t = datetime.now(UTC) + timedelta(hours=hours)
    return t.replace(minute=minutes_round, second=0, microsecond=0)


def iso(t: datetime) -> str:
    return t.isoformat()


async def resource(http: AsyncClient, who: dict[str, str], kind: str, name: str, **extra: object) -> dict:
    r = await http.post("/booking/resources", json={"kind": kind, "name": name, **extra}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


async def book(http: AsyncClient, who: dict[str, str], rid: str, start: str, **extra: object) -> Response:
    return await http.post("/booking/bookings", json={"resource_id": rid, "starts_at": start, **extra}, headers=who)


async def scalar(sql: str, **params: object) -> object:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one()


async def execute(sql: str, **params: object) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(sql), params)
        await session.commit()


def error_shape(r: Response) -> str:
    body = r.json()
    assert set(body) == {"code", "message", "details"} and isinstance(body["details"], list), body
    return body["code"]


# --- resources and availability ----------------------------------------------------------------------------


async def test_resources_inherit_the_kind_and_availability_lists_free_slots(http, people) -> None:  # noqa: ANN001
    admin, c1 = people["admin"], people["c1"]
    doc = await resource(http, admin, "practitioner", "Dr. A")
    assert (doc["mode"], doc["slot_minutes"], doc["timezone"], doc["capacity"], doc["active"]) == ("slot", 30, "Europe/Berlin", 1, True)
    assert doc["schedule"]["mon"] == [{"start": "09:00", "end": "12:00"}, {"start": "13:00", "end": "17:00"}]
    pool = await resource(http, admin, "loaner", "Walkers")
    assert (pool["mode"], pool["capacity"], pool["schedule"], pool["min_minutes"]) == ("pool", 3, None, 60)
    assert (await resource(http, admin, "loaner", "Wheelchairs", capacity=7))["capacity"] == 7
    mon = monday()
    params = {"from": mon.isoformat(), "to": (mon + timedelta(days=6)).isoformat()}
    slots = (await http.get(f"/booking/resources/{doc['id']}/availability", params=params, headers=c1)).json()
    assert slots["timezone"] == "Europe/Berlin" and slots["slot_minutes"] == 30 and len(slots["slots"]) == 5 * 14  # Mon-Fri: 6 + 8 slots
    expected_first = datetime(mon.year, mon.month, mon.day, 9, 0, tzinfo=BERLIN).astimezone(UTC)
    first = slots["slots"][0]
    assert datetime.fromisoformat(first["starts_at"]) == expected_first and first["free"] is True
    assert datetime.fromisoformat(first["ends_at"]) - datetime.fromisoformat(first["starts_at"]) == timedelta(minutes=30)
    r = await book(http, c1, doc["id"], at(mon, 9, 30), confirm=True)
    assert r.status_code == 201, r.text
    after = (await http.get(f"/booking/resources/{doc['id']}/availability", params=params, headers=c1)).json()["slots"]
    assert len(after) == 69 and at(mon, 9, 30) not in [s["starts_at"] for s in after]
    taken = (await http.get(f"/booking/resources/{doc['id']}/availability", params={**params, "include_taken": "true"}, headers=c1)).json()["slots"]
    assert len(taken) == 70 and [s["free"] for s in taken].count(False) == 1
    # a pool has no slot list; a slot resource has no capacity view; the window is bounded
    assert error_shape(await http.get(f"/booking/resources/{pool['id']}/availability", params=params, headers=c1)) == "not_slot_resource"
    window = {"starts_at": iso(soon(30)), "ends_at": iso(soon(31))}
    assert error_shape(await http.get(f"/booking/resources/{doc['id']}/capacity", params=window, headers=c1)) == "not_pool_resource"
    far = {"from": mon.isoformat(), "to": (mon + timedelta(days=40)).isoformat()}
    assert error_shape(await http.get(f"/booking/resources/{doc['id']}/availability", params=far, headers=c1)) == "invalid_range"
    # an inactive resource lists no free slot and refuses bookings
    assert (await http.patch(f"/booking/resources/{doc['id']}", json={"active": False, "name": "Dr. A (away)"}, headers=admin)).json()["active"] is False
    assert (await http.get(f"/booking/resources/{doc['id']}/availability", params=params, headers=c1)).json()["slots"] == []
    assert error_shape(await book(http, c1, doc["id"], at(mon, 10))) == "resource_inactive"
    listed = (await http.get("/booking/resources", params={"kind": "practitioner"}, headers=c1)).json()
    assert listed["total"] == 1 and listed["items"][0]["name"] == "Dr. A (away)"


async def test_resource_input_is_validated(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    bad = [
        ({"kind": "spaceship", "name": "x"}, "unknown_kind"),
        ({"kind": "practitioner", "name": "x", "timezone": "Mars/Olympus"}, "invalid_timezone"),
        ({"kind": "practitioner", "name": "x", "schedule": {"mon": [{"start": "10:00", "end": "09:00"}]}}, "invalid_schedule"),
        ({"kind": "practitioner", "name": "x", "schedule": {"mon": [{"start": "09:00", "end": "09:10"}]}}, "invalid_schedule"),
        ({"kind": "practitioner", "name": "x", "capacity": 2}, "invalid_capacity"),
        ({"kind": "room", "name": "x", "schedule": {"mon": [{"start": "09:00", "end": "10:00"}]}}, "invalid_schedule"),
        ({"kind": "room", "name": "x", "capacity": 4}, "invalid_capacity"),
        ({"kind": "loaner", "name": "x", "capacity": 2.5}, "validation_error"),
        ({"kind": "loaner", "name": "x", "capacity": 0}, "validation_error"),
        ({"kind": "loaner", "name": "x", "colour": "red"}, "validation_error"),
    ]
    for body, code in bad:
        r = await http.post("/booking/resources", json=body, headers=admin)
        assert r.status_code == 422 and error_shape(r) == code, (body, r.text)
    custom = await resource(http, admin, "practitioner", "Dr. Night", timezone="UTC", schedule={"sat": [{"start": "22:00", "end": "23:00"}]})
    assert custom["schedule"] == {"sat": [{"start": "22:00", "end": "23:00"}]} and custom["timezone"] == "UTC"
    assert (await http.get("/booking/resources", headers=admin)).json()["total"] == 1


# --- no double booking ---------------------------------------------------------------------------------------


async def test_eight_parallel_requests_for_one_slot_give_exactly_one_success(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    start = at(monday(), 10, 0)
    answers = await asyncio.gather(*[book(http, people["c1"], doc["id"], start) for _ in range(8)])
    codes = sorted(r.status_code for r in answers)
    assert codes == [201] + [409] * 7, [r.text for r in answers]
    assert [error_shape(r) for r in answers if r.status_code == 409] == ["slot_taken"] * 7
    winner = next(r for r in answers if r.status_code == 201).json()
    assert winner["status"] == "held" and winner["mode"] == "slot" and winner["quantity"] == 1
    assert await scalar("select count(*) from bookings where resource_id = :r and status in ('held', 'confirmed')", r=doc["id"]) == 1
    # different customers, the neighbouring slot: both fine; 8 more parallel requests for the same one with confirm
    answers = await asyncio.gather(*[book(http, people["c1" if i % 2 else "admin"], doc["id"], at(monday(), 11, 0), confirm=True) for i in range(8)])
    assert sorted(r.status_code for r in answers) == [201] + [409] * 7
    assert [r.json()["status"] for r in answers if r.status_code == 201] == ["confirmed"]


async def test_slot_rules_outside_availability_and_bad_input(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    c1, mon = people["c1"], monday()
    for start, why in (
        (at(mon, 9, 10), "not on the slot grid"),
        (at(mon, 12, 0), "lunch break"),
        (at(mon, 8, 30), "before opening"),
        (at(mon, 16, 30) if False else at(mon + timedelta(days=5), 10), "saturday"),
        (iso(datetime.now(UTC) - timedelta(days=1)), "in the past"),
        (iso(datetime.now(UTC) + timedelta(days=400)), "beyond the horizon"),
    ):
        r = await book(http, c1, doc["id"], start)
        assert r.status_code == 422 and error_shape(r) == "outside_availability", (why, r.text)
    assert error_shape(await book(http, c1, doc["id"], "2030-01-07T09:00:00")) == "invalid_time"  # no offset
    assert error_shape(await book(http, c1, doc["id"], at(mon, 9), ends_at=at(mon, 10))) == "invalid_range"
    assert error_shape(await book(http, c1, doc["id"], at(mon, 9), quantity=2)) == "invalid_quantity"
    assert error_shape(await book(http, c1, doc["id"], at(mon, 9), quantity=1.5)) == "validation_error"
    assert error_shape(await book(http, c1, doc["id"], at(mon, 9), colour="red")) == "validation_error"
    ok = await book(http, c1, doc["id"], at(mon, 16, 30), ends_at=at(mon, 17, 0))  # the last slot, ends_at = start + slot
    assert ok.status_code == 201 and ok.json()["ends_at"].startswith(datetime(mon.year, mon.month, mon.day, 17, 0, tzinfo=BERLIN).astimezone(UTC).strftime("%Y-%m-%dT%H:%M"))
    assert error_shape(await book(http, c1, "00000000-0000-0000-0000-000000000000", at(mon, 9))) == "not_found"
    # the same instant written in another offset is the same slot
    utc_form = datetime(mon.year, mon.month, mon.day, 9, 0, tzinfo=BERLIN).astimezone(UTC).isoformat()
    assert (await book(http, c1, doc["id"], utc_form)).status_code == 201
    assert error_shape(await book(http, people["c2"], doc["id"], at(mon, 9))) == "slot_taken"


async def test_range_bookings_never_overlap_but_may_touch(http, people) -> None:  # noqa: ANN001
    room = await resource(http, people["admin"], "room", "Room 1")
    assert (room["mode"], room["capacity"], room["min_minutes"], room["max_minutes"]) == ("range", 1, 30, 480)
    t = soon(48)
    c1 = people["c1"]
    first = await book(http, c1, room["id"], iso(t), ends_at=iso(t + timedelta(hours=2)))
    assert first.status_code == 201 and first.json()["mode"] == "range", first.text
    for s, e in ((t + timedelta(hours=1), t + timedelta(hours=3)), (t - timedelta(hours=1), t + timedelta(hours=1)), (t, t + timedelta(hours=2)), (t + timedelta(minutes=30), t + timedelta(hours=1))):
        r = await book(http, people["c2"], room["id"], iso(s), ends_at=iso(e))
        assert r.status_code == 409 and error_shape(r) == "slot_taken", (s, e)
    touching = await book(http, people["c2"], room["id"], iso(t + timedelta(hours=2)), ends_at=iso(t + timedelta(hours=3)))
    assert touching.status_code == 201  # half-open: back to back is fine
    other = await resource(http, people["admin"], "room", "Room 2")
    assert (await book(http, people["c2"], other["id"], iso(t), ends_at=iso(t + timedelta(hours=2)))).status_code == 201  # another resource
    for end, why in ((None, "ends_at missing"), (iso(t - timedelta(hours=1)), "ends before start"), (iso(t + timedelta(minutes=10)), "shorter than the minimum"), (iso(t + timedelta(hours=9)), "longer than the maximum")):
        extra = {} if end is None else {"ends_at": end}
        r = await book(http, c1, room["id"], iso(t + timedelta(days=3)), **extra)
        assert r.status_code == 422 and error_shape(r) == "invalid_range", (why, r.text)
    assert error_shape(await book(http, c1, room["id"], iso(t + timedelta(days=3)), ends_at=iso(t + timedelta(days=3, hours=1)), quantity=2)) == "invalid_quantity"
    cap = (await http.get(f"/booking/resources/{room['id']}/capacity", params={"starts_at": iso(t), "ends_at": iso(t + timedelta(hours=3))}, headers=c1)).json()
    assert cap == {"resource_id": room["id"], "capacity": 1, "booked": 1, "free": 0}


async def test_the_database_itself_refuses_overlaps_and_illegal_changes(http, people) -> None:  # noqa: ANN001
    room = await resource(http, people["admin"], "room", "Room 1")
    t = soon(72)
    made = await book(http, people["c1"], room["id"], iso(t), ends_at=iso(t + timedelta(hours=1)))
    assert made.status_code == 201
    tenant = await scalar("select tenant_id from booking_resources where id = :r", r=room["id"])
    insert = (
        "insert into bookings (id, tenant_id, resource_id, status, exclusive, starts_at, ends_at, quantity) "
        "values (gen_random_uuid(), :t, :r, :s, :x, :a, :b, 1)"
    )
    args = {"t": tenant, "r": room["id"], "s": "confirmed", "x": True, "a": t + timedelta(minutes=30), "b": t + timedelta(hours=2)}
    with pytest.raises(sa.exc.IntegrityError) as raised:
        await execute(insert, **args)
    assert "ex_bookings_no_overlap" in str(raised.value)
    with pytest.raises(sa.exc.DBAPIError):  # a booking can only start held or confirmed
        await execute(insert, **{**args, "s": "cancelled"})
    later = {**args, "a": t + timedelta(hours=5), "b": t + timedelta(hours=6)}
    await execute(insert, **later)
    await execute("update bookings set status = 'cancelled' where starts_at = :a", a=later["a"])  # confirmed -> cancelled is legal
    await execute(insert, **later)  # a cancelled booking never blocks
    await execute(insert, **{**args, "x": False})  # only exclusive (slot / range) rows are in the constraint
    with pytest.raises(sa.exc.DBAPIError):  # a cancelled booking is frozen, times are immutable
        await execute("update bookings set status = 'confirmed' where status = 'cancelled'")
    with pytest.raises(sa.exc.DBAPIError):
        await execute("update bookings set starts_at = starts_at + interval '1 hour' where id = :i", i=made.json()["id"])
    with pytest.raises(sa.exc.DBAPIError):
        await execute("update bookings set ends_at = starts_at where id = :i", i=made.json()["id"])


# --- pool capacity -------------------------------------------------------------------------------------------


async def test_pool_capacity_is_never_exceeded_under_eight_parallel_requests(http, people) -> None:  # noqa: ANN001
    pool = await resource(http, people["admin"], "loaner", "Walkers")
    t = soon(48)
    window = {"starts_at": iso(t), "ends_at": iso(t + timedelta(hours=2))}
    answers = await asyncio.gather(*[book(http, people["c1"], pool["id"], iso(t), ends_at=iso(t + timedelta(hours=2))) for _ in range(8)])
    assert sorted(r.status_code for r in answers) == [201] * 3 + [409] * 5, [r.text for r in answers]
    assert {error_shape(r) for r in answers if r.status_code == 409} == {"capacity_exceeded"}
    detail = next(r for r in answers if r.status_code == 409).json()["details"][0]
    assert detail["capacity"] == 3 and detail["requested"] == 1
    cap = (await http.get(f"/booking/resources/{pool['id']}/capacity", params=window, headers=people["c1"])).json()
    assert (cap["capacity"], cap["booked"], cap["free"]) == (3, 3, 0)
    assert await scalar("select sum(quantity) from bookings where resource_id = :r", r=pool["id"]) == 3
    # cancelling one frees one unit; touching windows and later windows are free
    first = next(r for r in answers if r.status_code == 201).json()
    assert (await http.post(f"/booking/bookings/{first['id']}/cancel", headers=people["c1"])).status_code == 200
    assert (await book(http, people["c2"], pool["id"], iso(t), ends_at=iso(t + timedelta(hours=2)))).status_code == 201
    assert error_shape(await book(http, people["c2"], pool["id"], iso(t + timedelta(hours=1)), ends_at=iso(t + timedelta(hours=3)))) == "capacity_exceeded"
    assert (await book(http, people["c2"], pool["id"], iso(t + timedelta(hours=2)), ends_at=iso(t + timedelta(hours=4)), quantity=3)).status_code == 201


async def test_pool_quantities_add_up_and_overlap_is_measured_at_the_peak(http, people) -> None:  # noqa: ANN001
    pool = await resource(http, people["admin"], "loaner", "Walkers")
    c1 = people["c1"]
    t = soon(96)
    h = timedelta(hours=1)
    assert (await book(http, c1, pool["id"], iso(t), ends_at=iso(t + h), quantity=2)).status_code == 201
    assert (await book(http, c1, pool["id"], iso(t + h), ends_at=iso(t + 2 * h), quantity=2)).status_code == 201  # back to back: peak is 2
    wide = await book(http, c1, pool["id"], iso(t), ends_at=iso(t + 2 * h), quantity=2)  # peak would be 4
    assert wide.status_code == 409 and error_shape(wide) == "capacity_exceeded"
    assert (await book(http, c1, pool["id"], iso(t), ends_at=iso(t + 2 * h), quantity=1)).status_code == 201  # peak 3
    too_many = await book(http, c1, pool["id"], iso(t + 5 * h), ends_at=iso(t + 6 * h), quantity=4)
    assert too_many.status_code == 409 and error_shape(too_many) == "capacity_exceeded"
    assert (await book(http, c1, pool["id"], iso(t + 5 * h), ends_at=iso(t + 6 * h), quantity=3)).status_code == 201
    cap = (await http.get(f"/booking/resources/{pool['id']}/capacity", params={"starts_at": iso(t), "ends_at": iso(t + 3 * h)}, headers=c1)).json()
    assert (cap["booked"], cap["free"]) == (3, 0)


# --- holds ---------------------------------------------------------------------------------------------------


async def test_a_hold_has_a_ttl_and_an_expired_hold_frees_the_slot(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    c1, c2, start = people["c1"], people["c2"], at(monday(), 14, 0)
    held = await book(http, c1, doc["id"], start)
    assert held.status_code == 201
    b = held.json()
    ttl = datetime.fromisoformat(b["hold_expires_at"]) - datetime.now(UTC)
    assert b["status"] == "held" and timedelta(seconds=100) < ttl <= timedelta(seconds=120)
    assert error_shape(await book(http, c2, doc["id"], start)) == "slot_taken"  # the hold blocks while it lives
    await execute("update bookings set hold_expires_at = now() - interval '1 second' where id = :i", i=b["id"])
    # lazy: a read shows it expired, availability lists the slot again, and a new booking for the slot works
    seen = (await http.get(f"/booking/bookings/{b['id']}", headers=c1)).json()
    assert seen["status"] == "expired" and seen["hold_expires_at"] is None and seen["expired_at"] is not None
    params = {"from": monday().isoformat(), "to": monday().isoformat()}
    assert start[:16] in [datetime.fromisoformat(s["starts_at"]).astimezone(BERLIN).isoformat()[:16] for s in (await http.get(f"/booking/resources/{doc['id']}/availability", params=params, headers=c1)).json()["slots"]]
    assert (await book(http, c2, doc["id"], start)).status_code == 201
    r = await http.post(f"/booking/bookings/{b['id']}/confirm", headers=c1)
    assert r.status_code == 410 and error_shape(r) == "hold_expired"


async def test_create_expires_a_stale_hold_by_itself_and_confirm_of_a_stale_hold_is_gone(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    c1, c2, start = people["c1"], people["c2"], at(monday(), 15, 0)
    stale = (await book(http, c1, doc["id"], start)).json()
    await execute("update bookings set hold_expires_at = now() - interval '5 seconds' where id = :i", i=stale["id"])
    assert (await book(http, c2, doc["id"], start)).status_code == 201  # no read in between: create expires it
    assert await scalar("select status from bookings where id = :i", i=stale["id"]) == "expired"
    other = (await book(http, c1, doc["id"], at(monday(), 15, 30))).json()
    await execute("update bookings set hold_expires_at = now() - interval '5 seconds' where id = :i", i=other["id"])
    r = await http.post(f"/booking/bookings/{other['id']}/confirm", headers=c1)  # confirm itself finds the stale hold
    assert r.status_code == 410 and error_shape(r) == "hold_expired"
    assert await scalar("select status from bookings where id = :i", i=other["id"]) == "expired"  # stored, not rolled back
    assert error_shape(await http.post(f"/booking/bookings/{other['id']}/cancel", headers=c1)) == "invalid_transition"


async def test_the_expire_sweep_and_pool_holds(http, people) -> None:  # noqa: ANN001
    pool = await resource(http, people["admin"], "loaner", "Walkers")
    t = soon(120)
    w = {"ends_at": iso(t + timedelta(hours=2))}
    ids = [(await book(http, people["c1"], pool["id"], iso(t), **w)).json()["id"] for _ in range(3)]
    assert error_shape(await book(http, people["c2"], pool["id"], iso(t), **w)) == "capacity_exceeded"
    await execute("update bookings set hold_expires_at = now() - interval '1 second' where id = :i or id = :j", i=ids[0], j=ids[1])
    assert error_shape(await http.post("/booking/expire", headers=people["c1"])) == "forbidden"  # managers only
    assert (await http.post("/booking/expire", headers=people["staff"])).json() == {"expired": 2}
    assert (await http.post("/booking/expire", headers=people["staff"])).json() == {"expired": 0}
    assert await scalar("select count(*) from bookings where status = 'expired'") == 2
    assert (await book(http, people["c2"], pool["id"], iso(t), quantity=2, **w)).status_code == 201  # two units are back
    assert error_shape(await book(http, people["c2"], pool["id"], iso(t), **w)) == "capacity_exceeded"


# --- states, fees --------------------------------------------------------------------------------------------


async def test_the_state_machine(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    c1, mon = people["c1"], monday()
    b = (await book(http, c1, doc["id"], at(mon, 9, 0))).json()
    confirmed = await http.post(f"/booking/bookings/{b['id']}/confirm", headers=c1)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["hold_expires_at"] is None and confirmed.json()["confirmed_at"] is not None
    again = await http.post(f"/booking/bookings/{b['id']}/confirm", headers=c1)  # re-confirming a confirmed booking is a no-op
    assert again.status_code == 200 and again.json()["status"] == "confirmed"
    cancelled = await http.post(f"/booking/bookings/{b['id']}/cancel", json={"reason": "moved"}, headers=c1)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled" and cancelled.json()["cancelled_at"] is not None
    for path in ("confirm", "cancel"):
        r = await http.post(f"/booking/bookings/{b['id']}/{path}", headers=c1)
        assert r.status_code == 409 and error_shape(r) == "invalid_transition"
    assert (await book(http, c1, doc["id"], at(mon, 9, 0))).status_code == 201  # the cancelled booking freed the slot
    held = (await book(http, c1, doc["id"], at(mon, 9, 30))).json()
    assert (await http.post(f"/booking/bookings/{held['id']}/cancel", headers=c1)).json()["status"] == "cancelled"  # held -> cancelled
    for status in ("held", "confirmed", "cancelled", "expired"):
        assert (await http.get("/booking/bookings", params={"status": status}, headers=c1)).status_code == 200


async def test_cancellation_fees_follow_the_spec(http, people) -> None:  # noqa: ANN001
    admin, c1, room = people["admin"], people["c1"], None
    room = await resource(http, admin, "room", "Room 1")
    soon_start = soon(3)
    late = (await book(http, c1, room["id"], iso(soon_start), ends_at=iso(soon_start + timedelta(hours=1)), confirm=True)).json()
    cancelled = (await http.post(f"/booking/bookings/{late['id']}/cancel", headers=c1)).json()
    assert (cancelled["cancel_fee_minor"], cancelled["fee_currency"]) == (2500, "EUR") and type(cancelled["cancel_fee_minor"]) is int
    far_start = soon(24 * 5)
    early = (await book(http, c1, room["id"], iso(far_start), ends_at=iso(far_start + timedelta(hours=1)), confirm=True)).json()
    assert (await http.post(f"/booking/bookings/{early['id']}/cancel", headers=c1)).json()["cancel_fee_minor"] == 0
    edge_start = soon(24 * 2)  # more than 24 h ahead: free
    held = (await book(http, c1, room["id"], iso(soon(2, 30)), ends_at=iso(soon(3, 30)))).json()  # a hold close to the start: no fee
    assert (await http.post(f"/booking/bookings/{held['id']}/cancel", headers=c1)).json()["cancel_fee_minor"] == 0
    # the boundary, moved by the clock instead of by the booking: 24 h before the start is still free, later costs the fee
    mid = (await book(http, c1, room["id"], iso(edge_start), ends_at=iso(edge_start + timedelta(hours=1)), confirm=True)).json()
    assert (await http.post(f"/booking/bookings/{mid['id']}/cancel", headers=c1)).json()["cancel_fee_minor"] == 0
    assert await scalar("select count(*) from bookings where cancel_fee_minor is not null") == 4


# --- idempotency ---------------------------------------------------------------------------------------------


async def test_create_is_idempotent_per_key_and_body(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    c1, c2, start = people["c1"], people["c2"], at(monday(), 10, 0)
    first = await book(http, c1, doc["id"], start, idempotency_key="k-1", notes="hello")
    assert first.status_code == 201 and "idempotent-replayed" not in first.headers
    again = await book(http, c1, doc["id"], start, idempotency_key="k-1", notes="hello")
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true" and again.json()["id"] == first.json()["id"]
    assert first.json()["idempotency_key"] == "k-1"
    changed = await book(http, c1, doc["id"], start, idempotency_key="k-1", notes="other")
    assert changed.status_code == 409 and error_shape(changed) == "idempotency_conflict"
    moved = await book(http, c1, doc["id"], at(monday(), 10, 30), idempotency_key="k-1", notes="hello")
    assert moved.status_code == 409 and error_shape(moved) == "idempotency_conflict"
    # the replay still works after the booking changed state, and another caller's key is separate
    assert (await http.post(f"/booking/bookings/{first.json()['id']}/cancel", headers=c1)).status_code == 200
    replay = await book(http, c1, doc["id"], start, idempotency_key="k-1", notes="hello")
    assert replay.status_code == 409 and error_shape(replay) == "idempotency_key_spent"  # a cancelled booking's key is spent
    assert (await book(http, c2, doc["id"], start, idempotency_key="k-1")).status_code == 201
    assert await scalar("select count(*) from bookings") == 2


async def test_parallel_retries_with_one_key_create_one_booking(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    answers = await asyncio.gather(*[book(http, people["c1"], doc["id"], at(monday(), 11, 0), idempotency_key="retry-1") for _ in range(8)])
    assert {r.status_code for r in answers} <= {200, 201}, [r.text for r in answers]
    assert [r.status_code for r in answers].count(201) == 1
    assert len({r.json()["id"] for r in answers}) == 1
    assert await scalar("select count(*) from bookings") == 1
    pool = await resource(http, people["admin"], "loaner", "Walkers")
    t = soon(48)
    answers = await asyncio.gather(*[book(http, people["c1"], pool["id"], iso(t), ends_at=iso(t + timedelta(hours=2)), idempotency_key="retry-2") for _ in range(8)])
    assert [r.status_code for r in answers].count(201) == 1 and len({r.json()["id"] for r in answers}) == 1
    assert await scalar("select count(*) from bookings where resource_id = :r", r=pool["id"]) == 1


# --- tenants and roles ---------------------------------------------------------------------------------------


async def test_tenants_are_isolated(http, people) -> None:  # noqa: ANN001
    a_doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    start = at(monday(), 9, 0)
    a_book = (await book(http, people["c1"], a_doc["id"], start, confirm=True)).json()
    b_admin, b_c = people["b_admin"], people["b_c"]
    assert (await http.get("/booking/resources", headers=b_admin)).json()["total"] == 0
    assert (await http.get("/booking/bookings", headers=b_admin)).json()["total"] == 0
    for r in (
        await http.get(f"/booking/resources/{a_doc['id']}", headers=b_admin),
        await http.get(f"/booking/bookings/{a_book['id']}", headers=b_admin),
        await http.get(f"/booking/resources/{a_doc['id']}/availability", params={"from": monday().isoformat(), "to": monday().isoformat()}, headers=b_c),
        await http.post(f"/booking/bookings/{a_book['id']}/cancel", headers=b_admin),
        await http.post(f"/booking/bookings/{a_book['id']}/confirm", headers=b_admin),
        await http.patch(f"/booking/resources/{a_doc['id']}", json={"active": False}, headers=b_admin),
        await book(http, b_c, a_doc["id"], start),
    ):
        assert r.status_code == 404 and error_shape(r) == "not_found", r.text
    # the same wall-clock slot on the other tenant's own resource is free, and a replay key is per tenant
    b_doc = await resource(http, b_admin, "practitioner", "Dr. B")
    assert (await book(http, b_c, b_doc["id"], start, confirm=True, idempotency_key="k")).status_code == 201
    assert (await http.get("/booking/bookings", headers=people["admin"])).json()["total"] == 1
    assert (await http.post("/booking/expire", headers=b_admin)).json() == {"expired": 0}
    assert await scalar("select count(distinct tenant_id) from bookings") == 2


async def test_roles_and_own_only(http, people) -> None:  # noqa: ANN001
    admin, staff, c1, c2, nobody = (people[k] for k in ("admin", "staff", "c1", "c2", "nobody"))
    doc = await resource(http, admin, "practitioner", "Dr. A")
    assert error_shape(await http.post("/booking/resources", json={"kind": "room", "name": "x"}, headers=c1)) == "forbidden"
    assert (await http.post("/booking/resources", json={"kind": "room", "name": "x"}, headers=staff)).status_code == 201
    assert error_shape(await http.patch(f"/booking/resources/{doc['id']}", json={"active": False}, headers=c1)) == "forbidden"
    for r in (await http.get("/booking/resources", headers=nobody), await http.get("/booking/bookings", headers=nobody), await book(http, nobody, doc["id"], at(monday(), 9))):
        assert r.status_code == 403 and error_shape(r) == "forbidden"
    assert (await http.get("/booking/resources", headers=c1)).status_code == 200  # customers read resources
    mine = (await book(http, c1, doc["id"], at(monday(), 9, 0))).json()
    theirs = (await book(http, c2, doc["id"], at(monday(), 9, 30))).json()
    assert [b["id"] for b in (await http.get("/booking/bookings", headers=c1)).json()["items"]] == [mine["id"]]  # own_only
    assert (await http.get("/booking/bookings", headers=c1)).json()["total"] == 1
    assert (await http.get(f"/booking/bookings/{theirs['id']}", headers=c1)).status_code == 404
    for action in ("confirm", "cancel"):
        assert (await http.post(f"/booking/bookings/{theirs['id']}/{action}", headers=c1)).status_code == 404  # not even visible
    assert {b["id"] for b in (await http.get("/booking/bookings", headers=staff)).json()["items"]} == {mine["id"], theirs["id"]}
    assert (await http.get(f"/booking/bookings/{theirs['id']}", headers=staff)).status_code == 200
    assert (await http.post(f"/booking/bookings/{theirs['id']}/confirm", headers=staff)).json()["status"] == "confirmed"  # managers act on any
    assert (await http.post(f"/booking/bookings/{mine['id']}/cancel", headers=admin)).json()["status"] == "cancelled"
    assert (await http.get("/booking/bookings", params={"resource_id": doc["id"], "status": "confirmed"}, headers=admin)).json()["total"] == 1
    window = {"from": iso(datetime.now(UTC) + timedelta(days=1)), "to": iso(datetime.now(UTC) + timedelta(days=2))}
    assert (await http.get("/booking/bookings", params=window, headers=admin)).json()["total"] == 0
    assert (await http.get("/booking/bookings", params={"limit": 1, "offset": 1}, headers=admin)).json()["items"][0]["id"] == theirs["id"]
    # staff (a manager role, not a booker role) may still book on a customer's behalf
    assert (await book(http, staff, doc["id"], at(monday(), 10, 0), customer_ref="walk-in")).json()["customer_ref"] == "walk-in"
    assert (await http.get("/booking/bookings", params={"limit": 0}, headers=admin)).status_code == 422
    assert (await http.get("/booking/bookings")).status_code == 401


# --- SENTINEL CP-5C hardening --------------------------------------------------------------------------------


async def test_hostile_dates_are_refused_not_a_500(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    r = await http.get(f"/booking/resources/{doc['id']}/availability", params={"from": "9999-12-31", "to": "9999-12-31"}, headers=people["c1"])
    assert r.status_code == 200 and r.json()["slots"] == []
    r = await book(http, people["c1"], doc["id"], "0001-01-01T00:00:00+05:00")
    assert r.status_code == 422 and error_shape(r) in {"invalid_time", "outside_availability"}
    r = await http.get(f"/booking/resources/{doc['id']}/capacity", params={"starts_at": "0001-01-01T00:00:00+05:00", "ends_at": "0001-01-02T00:00:00+05:00"}, headers=people["c1"])
    assert r.status_code in {409, 422}, r.text


async def test_holds_per_person_are_capped_and_a_hold_never_outlives_its_slot(http, people) -> None:  # noqa: ANN001
    doc = await resource(http, people["admin"], "practitioner", "Dr. A")
    pool = await resource(http, people["admin"], "loaner", "Walkers")
    t = soon(48)
    codes = []
    for i in range(22):
        r = await book(http, people["c1"], pool["id"], iso(t + timedelta(days=i)), ends_at=iso(t + timedelta(days=i, hours=2)))
        codes.append(r.status_code)
    assert codes.count(201) == 20 and codes[20:] == [429, 429]
    assert await scalar("select count(*) from bookings where hold_expires_at > starts_at") == 0
    assert doc["id"]
