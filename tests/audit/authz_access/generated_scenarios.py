"""Adversarial scenarios for the generated `realtime_metrics` project (Expense: owner-scoped for staff,
admin sees all, soft delete, cost_basis admin-only, state machine draft->approved; Payroll: admin only).
Copied into the project's tests/ by tests/audit/authz_access/test_generated_stack.py and run against a
real Postgres. Every test asserts the SAFE behaviour: a failure is a bug in the generated project."""

import asyncio
import base64
import json
import socket
import time

import httpx
import pytest
import sqlalchemy as sa
import uvicorn
from httpx import ASGITransport, AsyncClient

from app.auth.models import AuthUser
from app.db import session_factory
from app.main import app
from app.realtime import router as rt_router
from tests._auth_support import PASSWORD, outbox, sign_in  # noqa: F401

DUMMY = "00000000-0000-4000-8000-000000000009"


@pytest.fixture(autouse=True)
async def _fresh_state() -> None:
    rt_router.reset_state()
    async with session_factory() as session:
        await session.execute(sa.text("TRUNCATE TABLE rt_events, rt_floor"))
        await session.commit()


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "s1": await sign_in(http, "s1@example.com", roles=["staff"], n=0),
        "s2": await sign_in(http, "s2@example.com", roles=["staff"], n=1),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=2),
        "nobody": await sign_in(http, "nobody@example.com", roles=[], n=3),
    }


async def make(http: AsyncClient, who: dict[str, str], category: str = "food", amount: str = "10", **extra: object) -> dict:
    r = await http.post("/expenses", json={"category": category, "amount": amount, **extra}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


async def code(call: object) -> int:
    """Status of a request; an exception that escapes the app is what a server would answer with a 500."""
    try:
        return (await call).status_code  # type: ignore[misc, attr-defined]
    except Exception:  # noqa: BLE001
        return 599


# 1 -- another person's row: every verb, HEAD included, answers like "does not exist" ---------------------

async def test_other_owners_row_is_invisible_to_every_verb(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["s1"], "secretcat")
    url = f"/expenses/{row['id']}"
    s2 = people["s2"]
    ghost = f"/expenses/{DUMMY}"
    for method in ("HEAD", "GET", "DELETE"):
        a = (await http.request(method, url, headers=s2)).status_code
        b = (await http.request(method, ghost, headers=s2)).status_code
        assert a == b == 404, (method, a, b)
    assert (await http.put(url, json={"category": "x", "amount": "1"}, headers=s2)).status_code == 404
    assert (await http.patch(url, json={"category": "x"}, headers=s2)).status_code == 404
    assert (await http.post(f"{url}/transitions/approve", headers=s2)).status_code == 404
    assert (await http.get(f"{url}/transitions", headers=s2)).status_code == 404
    assert (await http.get(f"{url}/state-history", headers=s2)).status_code == 404
    mine = (await http.get(url, headers=people["s1"])).json()
    assert mine["category"] == "secretcat" and mine["status"] == "draft"


# 2 -- mass assignment ---------------------------------------------------------------------------------

async def test_state_machine_field_and_identity_columns_cannot_be_written(http, people) -> None:  # noqa: ANN001
    s1 = people["s1"]
    async with session_factory() as s:
        s2_id = (await s.execute(sa.select(AuthUser.id).where(AuthUser.email == "s2@example.com"))).scalar_one()
    forged = {"category": "c", "amount": "1", "status": "approved", "created_by_id": str(s2_id),
              "id": DUMMY, "deleted_at": None, "created_at": "2000-01-01T00:00:00Z"}
    r = await http.post("/expenses", json=forged, headers=s1)
    if r.status_code == 201:
        body = r.json()
        assert body["status"] == "draft", "status set at create skips the state machine"
        assert body["id"] != DUMMY
        assert (await http.get(f"/expenses/{body['id']}", headers=people["s2"])).status_code == 404, "row owned by s2"
    else:
        assert r.status_code == 422, r.text
    row = await make(http, s1)
    for call in (
        http.patch(f"/expenses/{row['id']}", json={"status": "approved"}, headers=s1),
        http.put(f"/expenses/{row['id']}", json={"category": "c", "amount": "1", "status": "approved"}, headers=s1),
        http.patch(f"/expenses/{row['id']}", json={"created_by_id": str(s2_id)}, headers=s1),
    ):
        resp = await call
        assert resp.status_code in (200, 422), resp.text
    now = (await http.get(f"/expenses/{row['id']}", headers=s1))
    assert now.status_code == 200, "the row must still be the caller's"
    assert now.json()["status"] == "draft"
    assert (await http.get(f"/expenses/{row['id']}", headers=people["s2"])).status_code == 404


async def test_register_cannot_choose_roles_or_verification(http) -> None:  # noqa: ANN001
    for extra in ({"roles": ["admin"]}, {"role": "admin"}, {"is_admin": True}, {"email_verified_at": "2020-01-01T00:00:00Z"},
                  {"is_active": True}, {"tenant_id": DUMMY}):
        r = await http.post("/auth/register", json={"email": "x@example.com", "password": PASSWORD, **extra})
        assert r.status_code == 422, (extra, r.status_code)
    async with session_factory() as s:
        n = (await s.execute(sa.select(sa.func.count()).select_from(AuthUser).where(AuthUser.email == "x@example.com"))).scalar_one()
    assert n == 0


# 3 -- role changes take effect on the very next request -----------------------------------------------

async def test_demoted_admin_token_stops_working_at_once(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    assert (await http.get("/payrolls", headers=admin)).status_code == 200
    async with session_factory() as s:
        await s.execute(sa.update(AuthUser).where(AuthUser.email == "admin@example.com").values(roles=["staff"]))
        await s.commit()
    assert (await http.get("/payrolls", headers=admin)).status_code == 403
    assert (await http.get("/metrics/payroll_total", headers=admin)).status_code == 403
    assert (await http.get("/payrolls/export.csv", headers=admin)).status_code == 403


async def test_deactivated_and_deleted_accounts_lose_their_token(http, people) -> None:  # noqa: ANN001
    async with session_factory() as s:
        await s.execute(sa.update(AuthUser).where(AuthUser.email == "s2@example.com").values(is_active=False))
        await s.commit()
    assert (await http.get("/expenses", headers=people["s2"])).status_code == 401
    assert (await http.delete("/auth/me", headers=people["s1"])).status_code == 204
    assert (await http.get("/expenses", headers=people["s1"])).status_code == 401


# 4 -- forged / confused tokens ------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


async def test_forged_and_confused_tokens_are_refused(http, people) -> None:  # noqa: ANN001
    access = people["s1"]["Authorization"].split(" ")[1]
    head, payload, sig = access.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["roles"] = ["admin"]
    forged_payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    none_head = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    tokens = {
        "tampered roles": f"{head}.{forged_payload}.{sig}",
        "alg none": f"{none_head}.{forged_payload}.",
        "alg none with sig": f"{none_head}.{forged_payload}.{sig}",
        "empty sig": f"{head}.{payload}.",
        "garbage": "a.b.c",
        "four parts": access + ".x",
    }
    login = await http.post("/auth/login", json={"email": "s1@example.com", "password": PASSWORD})
    tokens["refresh as access"] = login.json()["refresh_token"]
    bad = []
    for label, tok in tokens.items():
        status = await code(http.get("/payrolls", headers={"Authorization": f"Bearer {tok}"}))
        if status != 401:
            bad.append((label, status))
    assert bad == []


async def test_old_tokens_die_after_password_change_and_logout(http, people) -> None:  # noqa: ANN001
    login = await http.post("/auth/login", json={"email": "s1@example.com", "password": PASSWORD})
    old = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await http.get("/expenses", headers=old)).status_code == 200
    r = await http.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD + "-new"}, headers=old)
    assert r.status_code == 204, r.text
    assert (await http.get("/expenses", headers=old)).status_code == 401
    assert (await http.get("/expenses", headers=people["s1"])).status_code == 401
    refresh = await http.post("/auth/refresh", json={"refresh_token": login.json()["refresh_token"]})
    assert refresh.status_code == 401


# 5 -- a person with no role at all --------------------------------------------------------------------

async def test_a_person_without_roles_gets_nothing_anywhere(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["s1"])
    n = people["nobody"]
    routes = [
        ("GET", "/expenses"), ("POST", "/expenses"), ("GET", f"/expenses/{row['id']}"), ("HEAD", f"/expenses/{row['id']}"),
        ("PATCH", f"/expenses/{row['id']}"), ("PUT", f"/expenses/{row['id']}"), ("DELETE", f"/expenses/{row['id']}"),
        ("GET", "/expenses/export.csv"), ("POST", "/expenses/import"), ("GET", "/payrolls"), ("GET", "/payrolls/export.csv"),
        ("GET", f"/expenses/{row['id']}/transitions"), ("POST", f"/expenses/{row['id']}/transitions/approve"),
        ("GET", f"/expenses/{row['id']}/state-history"), ("GET", "/metrics/expense_total"), ("GET", "/metrics/expense_count"),
    ]
    bad = []
    for m, p in routes:
        r = await http.request(m, p, headers=n, json={"category": "x", "amount": "1"} if m in ("POST", "PUT", "PATCH") and "import" not in p else None)
        if r.status_code not in (401, 403, 404, 422) or (r.status_code == 200):
            bad.append((m, p, r.status_code))
    assert bad == []
    keys = (await http.get("/metrics", headers=n))
    assert keys.status_code in (200, 403) and (keys.status_code == 403 or keys.json() == [] or "expense_total" not in str(keys.json()))


async def test_head_on_admin_only_entity_never_reveals_existence(http, people) -> None:  # noqa: ANN001
    p = (await http.post("/payrolls", json={"person": "A", "salary": "1"}, headers=people["admin"])).json()
    a = (await http.head(f"/payrolls/{p['id']}", headers=people["s1"])).status_code
    b = (await http.head(f"/payrolls/{DUMMY}", headers=people["s1"])).status_code
    assert a == b == 403, (a, b)
    assert (await http.head(f"/payrolls/{p['id']}")).status_code == 401


# 6 -- export / import ---------------------------------------------------------------------------------

async def test_export_is_scoped_to_rows_and_fields_of_the_caller(http, people) -> None:  # noqa: ANN001
    await make(http, people["s1"], "mine-cat")
    await make(http, people["s2"], "theirs-cat")
    await make(http, people["admin"], "admin-cat", cost_basis="123.456")
    s1 = await http.get("/expenses/export.csv", headers=people["s1"])
    assert s1.status_code == 200
    assert "mine-cat" in s1.text and "theirs-cat" not in s1.text and "admin-cat" not in s1.text
    assert "cost_basis" not in s1.text.splitlines()[0] and "123.456" not in s1.text
    assert "Content-Disposition" in s1.headers or "content-disposition" in s1.headers
    assert (await http.get("/payrolls/export.csv", headers=people["s1"])).status_code == 403
    assert (await http.get("/expenses/export.csv")).status_code == 401


async def test_import_cannot_write_hidden_fields_or_forbidden_entities(http, people) -> None:  # noqa: ANN001
    csv = b"category,amount,cost_basis\nimported,5,999.5\n"
    r = await http.post("/expenses/import", files={"file": ("e.csv", csv, "text/csv")}, headers=people["s1"])
    assert r.status_code in (200, 422), r.text
    rows = (await http.get("/expenses", headers=people["admin"])).json()["items"]
    for item in rows:
        assert str(item.get("cost_basis")) not in ("999.5", "999.500000"), "staff wrote an admin-only field via import"
    pr = await http.post("/payrolls/import", files={"file": ("p.csv", b"person,salary\nX,1\n", "text/csv")}, headers=people["s1"])
    assert pr.status_code == 403
    assert (await http.get("/payrolls", headers=people["admin"])).json()["total"] == 0
    anon = await http.post("/expenses/import", files={"file": ("e.csv", csv, "text/csv")})
    assert anon.status_code == 401


async def test_import_oversize_and_formula_cells(http, people) -> None:  # noqa: ANN001
    big = b"category,amount\n" + b"x,1\n" * 3_000_000
    status = await code(http.post("/expenses/import", files={"file": ("big.csv", big, "text/csv")}, headers=people["s1"]))
    assert status in (413, 422), status
    await make(http, people["s1"], "=cmd|'/c calc'!A1")
    out = (await http.get("/expenses/export.csv", headers=people["s1"])).text
    assert "\n=cmd" not in out and ",=cmd" not in out, "formula cell not neutralised"


# 7 -- soft delete, filters, paging --------------------------------------------------------------------

async def test_deleted_rows_stay_gone_for_every_reader(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["s1"], "gonecat", "77")
    assert (await http.delete(f"/expenses/{row['id']}", headers=people["s1"])).status_code == 204
    for who in ("s1", "admin"):
        h = people[who]
        assert (await http.get(f"/expenses/{row['id']}", headers=h)).status_code == 404
        assert (await http.head(f"/expenses/{row['id']}", headers=h)).status_code == 404
        assert (await http.patch(f"/expenses/{row['id']}", json={"category": "z"}, headers=h)).status_code == 404
        assert (await http.post(f"/expenses/{row['id']}/transitions/approve", headers=h)).status_code == 404
        for q in ("include_deleted=true", "deleted=true", "with_deleted=1"):
            body = (await http.get(f"/expenses?{q}", headers=h)).json()
            assert "gonecat" not in str(body), q
        assert "gonecat" not in (await http.get("/expenses/export.csv", headers=h)).text
    assert (await http.get("/metrics/expense_count", headers=people["admin"])).json()["value"] == 0


async def test_unknown_hidden_and_identity_filters_never_widen_or_leak(http, people) -> None:  # noqa: ANN001
    mine = await make(http, people["s1"], "mine")
    theirs = await make(http, people["s2"], "theirs")
    adm = await make(http, people["admin"], "adm", cost_basis="55")
    s1 = people["s1"]
    async with session_factory() as s:
        s2_id = (await s.execute(sa.select(AuthUser.id).where(AuthUser.email == "s2@example.com"))).scalar_one()
    bad = []
    for q in ("cost_basis=55", "sort=cost_basis", "sort=-cost_basis", f"created_by_id={s2_id}", f"id={theirs['id']}",
              "sort=created_by_id", "sort=nonexistent", "category=theirs", "category=theirs&category=mine", "q=theirs",
              "category[ne]=x", "category__ne=x", "category=%", "limit=1&category=theirs"):
        r = await http.get(f"/expenses?{q}", headers=s1)
        text = r.text
        if r.status_code >= 500 or ("theirs" in text and "category=theirs" not in q):
            bad.append((q, r.status_code))
        if r.status_code == 200:
            assert theirs["id"] not in text and adm["id"] not in text, q
            assert '"cost_basis"' not in text, q
    assert bad == []
    assert mine["id"]


async def test_paging_boundaries_never_500(http, people) -> None:  # noqa: ANN001
    await make(http, people["s1"])
    bad = []
    for q in ("limit=0", "limit=-1", "limit=1000000000", "limit=abc", "offset=-1", "offset=99999999999999999999",
              "offset=9223372036854775808", "limit=1e3", "limit=1&limit=2", "offset=1.5"):
        status = await code(http.get(f"/expenses?{q}", headers=people["s1"]))
        if status >= 500:
            bad.append((q, status))
    assert bad == []
    r = await http.get("/expenses?limit=100000", headers=people["admin"])
    assert r.status_code == 422 or len(r.json()["items"]) <= 1000


async def test_malformed_ids_and_bodies_are_422_not_500(http, people) -> None:  # noqa: ANN001
    s1 = people["s1"]
    bad = []
    for m, p, body in (
        ("GET", "/expenses/not-a-uuid", None), ("HEAD", "/expenses/not-a-uuid", None), ("DELETE", "/expenses/%00", None),
        ("POST", "/expenses", {"category": "x" * 100000, "amount": "1"}), ("POST", "/expenses", {"category": "c", "amount": "1e999999"}),
        ("POST", "/expenses", {"category": "c", "amount": "NaN"}), ("POST", "/expenses", {"category": "\x00", "amount": "1"}),
        ("POST", "/expenses", [1, 2]), ("PATCH", f"/expenses/{DUMMY}", {"category": None}),
        ("POST", "/expenses", {"category": "c", "amount": "1", "qty": 2**40}),
    ):
        status = await code(http.request(m, p, json=body, headers=s1))
        if status >= 500:
            bad.append(f"{m} {p[:20]} {str(body)[-50:]} -> {status}")
    assert bad == []


# 8 -- concurrency -------------------------------------------------------------------------------------

async def test_parallel_foreign_writes_all_fail_and_change_nothing(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["s1"], "orig")
    url = f"/expenses/{row['id']}"
    calls = [http.patch(url, json={"category": f"evil{i}"}, headers=people["s2"]) for i in range(4)]
    calls += [http.delete(url, headers=people["s2"]) for _ in range(4)]
    codes = await asyncio.gather(*(code(c) for c in calls))
    assert set(codes) == {404}, codes
    assert (await http.get(url, headers=people["s1"])).json()["category"] == "orig"


async def test_parallel_owner_deletes_one_wins(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["s1"])
    codes = sorted(await asyncio.gather(*(code(http.delete(f"/expenses/{row['id']}", headers=people["s1"])) for _ in range(8))))
    assert set(codes) <= {204, 404}, codes
    assert 204 in codes
    assert (await http.get(f"/expenses/{row['id']}", headers=people["s1"])).status_code == 404


async def test_parallel_transitions_apply_once(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["s1"])
    codes = sorted(await asyncio.gather(*(code(http.post(f"/expenses/{row['id']}/transitions/approve", headers=people["s1"])) for _ in range(8))))
    assert 500 not in codes and 599 not in codes, codes
    log = (await http.get(f"/expenses/{row['id']}/state-history", headers=people["s1"])).json()
    approved = [c for c in log if c["to_state"] == "approved"]
    assert codes.count(200) == 1 and len(approved) == 1, f"codes={codes} approve rows={len(approved)}"


# 9 -- metrics -----------------------------------------------------------------------------------------

async def test_metric_query_params_cannot_redirect_the_aggregate(http, people) -> None:  # noqa: ANN001
    await make(http, people["s1"], "a", "1")
    await make(http, people["s2"], "b", "1000")
    await http.post("/payrolls", json={"person": "P", "salary": "5000"}, headers=people["admin"])
    s1 = people["s1"]
    for q in ("", "?entity=Payroll", "?field=salary", "?group_by=cost_basis", "?owner=all", "?created_by_id=x", "?filter=1=1"):
        r = await http.get(f"/metrics/expense_total{q}", headers=s1)
        assert r.status_code in (200, 400, 403, 422), (q, r.status_code)
        if r.status_code == 200:
            assert r.json()["value"] == "1", (q, r.json())
    for key in ("../payroll_total", "payroll_total%00", "PAYROLL_TOTAL", "payroll_total/", "payroll_total;"):
        r = await http.get(f"/metrics/{key}", headers=s1)
        assert r.status_code in (403, 404, 307, 308, 422), (key, r.status_code)
        assert "5000" not in r.text


# 10 -- realtime ---------------------------------------------------------------------------------------

@pytest.fixture
async def server():  # noqa: ANN201
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    await task


async def _listen(base: str, headers: dict[str, str], seconds: float, params: dict[str, str] | None = None) -> tuple[int, str]:
    raw = ""
    async with httpx.AsyncClient(timeout=None) as c:
        try:
            async with c.stream("GET", f"{base}/realtime/stream", headers=headers, params=params) as r:
                if r.status_code != 200:
                    return r.status_code, ""
                deadline = time.monotonic() + seconds
                it = r.aiter_lines()
                while time.monotonic() < deadline:
                    try:
                        raw += (await asyncio.wait_for(it.__anext__(), max(0.05, deadline - time.monotonic()))) + "\n"
                    except (TimeoutError, StopAsyncIteration):
                        break
        except httpx.HTTPError:
            pass
    return 200, raw


async def test_stream_replay_and_roleless_callers_never_see_foreign_rows(http, people, server) -> None:  # noqa: ANN001
    row = await make(http, people["s1"], "replaycat")
    await asyncio.sleep(1.0)
    status, raw = await _listen(server, {**people["s2"], "Last-Event-ID": "0"}, 2.0)
    assert row["id"] not in raw, "s2 replayed s1's event from the start of the log"
    status, raw = await _listen(server, people["s2"], 2.0, {"last_event_id": "0"})
    assert row["id"] not in raw
    status, raw = await _listen(server, people["nobody"], 2.0)
    assert status in (401, 403) or row["id"] not in raw, "a roleless caller received events"
    assert (await _listen(server, {}, 1.0))[0] == 401
    status, raw = await _listen(server, {**people["s1"], "Last-Event-ID": "x" * 500}, 1.0)
    assert status in (200, 400, 422)
