"""Scenario tests for the generated `runtime_config` project (orders). Copied into the project's tests/
folder by tests/e2e/test_runtime_config_stack.py and run against a real Postgres.

Rules under test: a sequence number is consumed only when the surrounding transaction commits (no gaps and
no duplicates under parallel inserts, a rollback burns nothing); counters can be per tenant or per year;
list edits and setting values are scoped to the caller's tenant; a role gate decides who may edit;
wrongly typed setting values are refused with 422.
"""

import asyncio
import datetime as dt
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.auth.models import AuthUser
from app.db import session_factory
from app.main import app
from app.models.orders import Order
from app.runtime_config import sequences, settings

PARALLEL = 60


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def tenant_of(email: str) -> uuid.UUID:
    async with session_factory() as session:
        user = (await session.execute(select(AuthUser).where(AuthUser.email == email))).scalar_one()
        return user.tenant_id


async def place_order(tenant: uuid.UUID, sequence: str, *, fail: bool = False, pause: float = 0.0) -> str:
    """One order with the next number of `sequence`, all in ONE transaction."""
    async with session_factory() as session:
        number = await sequences.next_number(session, sequence, tenant_id=tenant)
        if pause:
            await asyncio.sleep(pause)  # keep the lock a while so the others really queue up
        session.add(
            Order(customer="c", total=Decimal("1.00"), status="new", invoice_no=number, tenant_id=tenant)
        )
        if fail:
            await session.rollback()
            return number
        await session.commit()
        return number


# --- sequences -------------------------------------------------------------------------------------------


async def test_parallel_inserts_get_no_gaps_and_no_duplicates(http) -> None:  # noqa: ANN001
    await sign_in(http, "a-admin@example.com", roles=["admin"], n=0)
    tenant = await tenant_of("a-admin@example.com")
    numbers = await asyncio.gather(
        *(place_order(tenant, "order_no", pause=0.005) for _ in range(PARALLEL))
    )
    year = dt.datetime.now(dt.UTC).year
    assert len(set(numbers)) == PARALLEL  # no duplicate
    assert sorted(numbers) == [f"ORD-{year}-{n:04d}" for n in range(1, PARALLEL + 1)]  # no gap
    async with session_factory() as session:
        stored = (await session.execute(select(Order.invoice_no))).scalars().all()
        assert sorted(stored) == sorted(numbers)
    # a second wave carries on where the first stopped
    more = await asyncio.gather(*(place_order(tenant, "order_no") for _ in range(10)))
    assert sorted(more) == [f"ORD-{year}-{n:04d}" for n in range(PARALLEL + 1, PARALLEL + 11)]


async def test_a_rolled_back_transaction_does_not_burn_a_number(http) -> None:  # noqa: ANN001
    await sign_in(http, "b-admin@example.com", roles=["admin"], n=1)
    tenant = await tenant_of("b-admin@example.com")
    year = dt.datetime.now(dt.UTC).year
    assert await place_order(tenant, "order_no") == f"ORD-{year}-0001"
    lost = await place_order(tenant, "order_no", fail=True)  # taken, then rolled back
    assert lost == f"ORD-{year}-0002"
    assert await place_order(tenant, "order_no") == f"ORD-{year}-0002"  # the same number comes back
    # an error raised half way through behaves the same
    with pytest.raises(RuntimeError):
        async with session_factory() as session:
            await sequences.next_number(session, "order_no", tenant_id=tenant)
            raise RuntimeError("boom")
    assert await place_order(tenant, "order_no") == f"ORD-{year}-0003"
    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
    assert count == 3


async def test_counters_are_per_tenant_where_the_spec_says_so(http) -> None:  # noqa: ANN001
    await sign_in(http, "c-admin@example.com", roles=["admin"], n=2)
    await sign_in(http, "d-admin@example.com", roles=["admin"], n=3)
    first, second = await tenant_of("c-admin@example.com"), await tenant_of("d-admin@example.com")
    assert first != second
    got_first = await asyncio.gather(*(place_order(first, "invoice_no") for _ in range(7)))
    got_second = await asyncio.gather(*(place_order(second, "invoice_no") for _ in range(3)))
    assert sorted(got_first) == [f"INV-{n:05d}" for n in range(1, 8)]
    assert sorted(got_second) == [f"INV-{n:05d}" for n in range(1, 4)]  # independent of the other tenant
    # the global sequence is shared by both
    year = dt.datetime.now(dt.UTC).year
    assert await place_order(first, "order_no") == f"ORD-{year}-0001"
    assert await place_order(second, "order_no") == f"ORD-{year}-0002"
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await sequences.next_number(session, "invoice_no")  # a per-tenant counter needs a tenant
        with pytest.raises(ValueError):
            await sequences.next_number(session, "nope")


async def test_yearly_counters_restart_each_year(http) -> None:  # noqa: ANN001
    await sign_in(http, "e-admin@example.com", roles=["admin"], n=4)
    tenant = await tenant_of("e-admin@example.com")
    years = (dt.datetime(2030, 6, 1, tzinfo=dt.UTC), dt.datetime(2031, 1, 1, tzinfo=dt.UTC))
    got = []
    for now in (years[0], years[0], years[1], years[0]):
        async with session_factory() as session:
            got.append(await sequences.next_number(session, "order_no", tenant_id=tenant, now=now))
            await session.commit()
    assert got == ["ORD-2030-0001", "ORD-2030-0002", "ORD-2031-0001", "ORD-2030-0003"]


async def test_sequence_counters_are_shown_only_to_their_roles(http) -> None:  # noqa: ANN001
    admin = await sign_in(http, "f-admin@example.com", roles=["admin"], n=5)
    member = await sign_in(http, "f-member@example.com", roles=["member"], n=6, join="f-admin@example.com")
    tenant = await tenant_of("f-admin@example.com")
    await place_order(tenant, "invoice_no")
    shown = (await http.get("/config/sequences", headers=admin)).json()
    assert shown == [
        {"name": "invoice_no", "per_tenant": True, "reset_yearly": False, "next_number": "INV-00002"}
    ]  # order_no lists no view_roles: nobody sees it here
    assert (await http.get("/config/sequences", headers=member)).json() == []
    assert (await http.get("/config/sequences")).status_code == 401


# --- lists -----------------------------------------------------------------------------------------------


async def test_list_edits_stay_inside_the_tenant(http) -> None:  # noqa: ANN001
    one = await sign_in(http, "g-admin@example.com", roles=["admin"], n=7)
    two = await sign_in(http, "h-admin@example.com", roles=["admin"], n=8)
    url = "/config/lists/order_status"
    added = await http.put(
        f"{url}/items/backordered", json={"label": "Backordered", "color": "#ff00aa"}, headers=one
    )
    assert added.status_code == 200, added.text
    relabel = await http.put(f"{url}/items/packed", json={"label": "Boxed up", "color": None}, headers=one)
    assert relabel.status_code == 200
    mine = {i["value"]: i for i in (await http.get(url, headers=one)).json()["items"]}
    theirs = {i["value"]: i for i in (await http.get(url, headers=two)).json()["items"]}
    assert set(mine) == {"new", "packed", "shipped", "cancelled", "backordered"}
    assert mine["backordered"]["system"] is False and mine["packed"]["label"] == "Boxed up"
    assert set(theirs) == {"new", "packed", "shipped", "cancelled"}  # the other tenant is untouched
    assert theirs["packed"]["label"] == "Packed" and theirs["packed"]["color"] == "#d97706"
    # tenant two cannot reach tenant one's value, and deleting it changes nothing for tenant one
    assert (await http.delete(f"{url}/items/backordered", headers=two)).status_code == 404
    assert "backordered" in {i["value"] for i in (await http.get(url, headers=one)).json()["items"]}
    # removing the override puts the system value back; removing a custom value deletes it
    assert (await http.delete(f"{url}/items/packed", headers=one)).status_code == 204
    assert (await http.delete(f"{url}/items/backordered", headers=one)).status_code == 204
    back = {i["value"]: i for i in (await http.get(url, headers=one)).json()["items"]}
    assert set(back) == {"new", "packed", "shipped", "cancelled"} and back["packed"]["label"] == "Packed"


async def test_list_rules_roles_locks_and_limits(http) -> None:  # noqa: ANN001
    admin = await sign_in(http, "i-admin@example.com", roles=["admin"], n=9)
    member = await sign_in(http, "i-member@example.com", roles=["member"], n=10, join="i-admin@example.com")
    url = "/config/lists/order_status"
    assert (await http.get(url, headers=member)).json()["editable"] is False  # anyone may read
    refused = await http.put(f"{url}/items/extra", json={"label": "Extra"}, headers=member)
    assert refused.status_code == 403
    locked = await http.put(f"{url}/items/new", json={"label": "New", "active": False}, headers=admin)
    assert locked.status_code == 422 and locked.json()["code"] == "item_locked"
    off = await http.put(f"{url}/items/shipped", json={"label": "Shipped", "active": False}, headers=admin)
    assert off.status_code == 200
    assert next(i for i in off.json()["items"] if i["value"] == "shipped")["active"] is False
    for bad in ({"label": ""}, {"label": "x" * 81}, {"label": "ok", "color": "red"}):
        assert (await http.put(f"{url}/items/okay", json=bad, headers=admin)).status_code == 422
    assert (await http.put(f"{url}/items/Bad-Value", json={"label": "x"}, headers=admin)).status_code == 422
    assert (await http.put("/config/lists/ghost/items/x", json={"label": "x"}, headers=admin)).status_code == 404
    for n in range(8):  # 4 system values + 8 = the limit of 12
        assert (await http.put(f"{url}/items/v{n}", json={"label": f"V{n}"}, headers=admin)).status_code == 200
    full = await http.put(f"{url}/items/one_too_many", json={"label": "Too many"}, headers=admin)
    assert full.status_code == 422 and full.json()["code"] == "list_full"
    assert (await http.put(f"{url}/items/v0", json={"label": "Renamed"}, headers=admin)).status_code == 200


# --- settings --------------------------------------------------------------------------------------------


async def test_settings_are_typed_range_checked_and_role_gated(http) -> None:  # noqa: ANN001
    admin = await sign_in(http, "j-admin@example.com", roles=["admin"], n=11)
    member = await sign_in(http, "j-member@example.com", roles=["member"], n=12, join="j-admin@example.com")
    shown = {s["key"]: s for s in (await http.get("/config/settings", headers=admin)).json()}
    assert shown["vat_rate"]["value"] == "0.20" and shown["vat_rate"]["is_default"] is True
    assert shown["vat_rate"]["editable"] is True
    seen_by_member = {s["key"] for s in (await http.get("/config/settings", headers=member)).json()}
    assert "approval_threshold" not in seen_by_member  # read_roles: manager and admin only
    assert {"vat_rate", "allow_backorders", "invoice_footer"} <= seen_by_member
    put = lambda key, value, who=admin: http.put(f"/config/settings/{key}", json={"value": value}, headers=who)  # noqa: E731
    assert (await put("vat_rate", "0.25")).json()["value"] == "0.25"
    assert (await put("vat_rate", "1")).json()["value"] == "1"
    for key, bad in [
        ("vat_rate", 0.25),  # floats are refused: send decimals as strings
        ("vat_rate", "abc"),
        ("vat_rate", "1.01"),  # above the maximum
        ("vat_rate", "-0.1"),  # below the minimum
        ("vat_rate", True),
        ("vat_rate", None),
        ("approval_threshold", "500"),
        ("approval_threshold", 1.5),
        ("approval_threshold", True),
        ("approval_threshold", -1),
        ("approval_threshold", 1000001),
        ("allow_backorders", "yes"),
        ("allow_backorders", 1),
        ("invoice_footer", 7),
        ("invoice_footer", "x" * 121),
    ]:
        refused = await put(key, bad)
        assert refused.status_code == 422, (key, bad, refused.text)
        assert refused.json()["code"] == "invalid_value"
    assert (await put("approval_threshold", 2500)).json()["value"] == 2500  # an admin holds manager rights too
    assert (await put("vat_rate", "0.30", member)).status_code == 403  # wrong role
    assert (await put("nope", "x")).status_code == 404
    assert (await http.put("/config/settings/vat_rate", json={}, headers=admin)).status_code == 422
    assert (await http.get("/config/settings")).status_code == 401
    # nothing refused above changed the stored values
    now = {s["key"]: s["value"] for s in (await http.get("/config/settings", headers=admin)).json()}
    assert now["vat_rate"] == "1" and now["approval_threshold"] == 2500 and now["allow_backorders"] is False
    # deleting resets to the default
    assert (await http.delete("/config/settings/vat_rate", headers=admin)).status_code == 204
    reset = {s["key"]: s for s in (await http.get("/config/settings", headers=admin)).json()}
    assert reset["vat_rate"]["value"] == "0.20" and reset["vat_rate"]["is_default"] is True


async def test_setting_values_are_per_tenant_and_readable_by_code(http) -> None:  # noqa: ANN001
    one = await sign_in(http, "k-admin@example.com", roles=["admin"], n=13)
    await sign_in(http, "l-admin@example.com", roles=["admin"], n=14)
    first, second = await tenant_of("k-admin@example.com"), await tenant_of("l-admin@example.com")
    assert (await http.put("/config/settings/vat_rate", json={"value": "0.05"}, headers=one)).status_code == 200
    async with session_factory() as session:
        assert await settings.get_setting(session, "vat_rate", first) == Decimal("0.05")
        assert await settings.get_setting(session, "vat_rate", second) == Decimal("0.20")  # the default
        assert await settings.get_setting(session, "allow_backorders", second) is False
        with pytest.raises(ValueError):
            await settings.get_setting(session, "nope", second)


async def test_nul_and_bidi_characters_are_refused_never_a_500(http) -> None:  # noqa: ANN001
    admin = await sign_in(http, "m-admin@example.com", roles=["admin"], n=15)
    url = "/config/lists/order_status/items"
    for label in ("a\x00b", "\x00", "x\u202ey", "x\u202ay", "x\u2066y", "x\u2069y"):
        refused = await http.put(f"{url}/okay", json={"label": label}, headers=admin)
        assert refused.status_code == 422, (label, refused.status_code, refused.text)
        assert refused.json()["code"] == "invalid_value"
    for color in ("#ab\x00def", "#12345\u202e"):
        assert (await http.put(f"{url}/okay", json={"label": "ok", "color": color}, headers=admin)).status_code == 422
    for value in ("a%00b", "ok%00", "ok%E2%80%AE"):  # percent-encoded: the value in the path
        assert (await http.put(f"{url}/{value}", json={"label": "x"}, headers=admin)).status_code in (404, 422)
    refused = await http.put("/config/settings/invoice_footer", json={"value": "a\x00b"}, headers=admin)
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_value"
    # HTML is stored verbatim (clients must escape it when they show it), and nothing above was stored
    html = await http.put(f"{url}/okay", json={"label": "<img onerror=x>"}, headers=admin)
    assert html.status_code == 200
    labels = {i["value"]: i["label"] for i in html.json()["items"]}
    assert labels["okay"] == "<img onerror=x>"
    footer = {s["key"]: s["value"] for s in (await http.get("/config/settings", headers=admin)).json()}
    assert "\x00" not in footer["invoice_footer"]
