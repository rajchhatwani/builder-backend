"""Scenario tests for the generated `tenant_guard` project (copied into the project's tests/ by
tests/e2e/test_tenant_guard_stack.py, run against a real Postgres and a real uvicorn server).

Multi-tenant Employee: salary readable by hr + admin (written by hr), notes readable by hr. Proves that
(1) HEAD / DELETE follow the entity's access, (2) a caller without field access never sees a guarded value in
transition responses, the documents router or the change history, and (3) tenant A never sees tenant B rows,
hits, events or metrics through realtime, search and metrics.
"""

import asyncio
import io
import json
import socket

import httpx
import pytest
import sqlalchemy as sa
import uvicorn
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from app.db import session_factory
from app.main import app
from app.realtime import router as rt_router
from tests._auth_support import outbox, sign_in  # noqa: F401

SECRET_SALARY = 7654321
SECRET_NOTE = "NOTESECRET-77"


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
        "a_staff": await sign_in(http, "a_staff@example.com", roles=["staff"], n=0),
        "a_hr": await sign_in(http, "a_hr@example.com", roles=["hr"], n=1, join="a_staff@example.com"),
        "b_staff": await sign_in(http, "b_staff@example.com", roles=["staff"], n=2),
        "b_hr": await sign_in(http, "b_hr@example.com", roles=["hr"], n=3, join="b_staff@example.com"),
        "nobody": await sign_in(http, "nobody@example.com", roles=[], n=4, join="a_staff@example.com"),
    }


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


class Stream:
    """One SSE client collecting frames in the background."""

    def __init__(self, base: str, headers: dict[str, str]) -> None:
        self.headers = dict(headers)
        self.url = f"{base}/realtime/stream"
        self.events: list[dict] = []
        self.raw = ""
        self.opened = asyncio.Event()

    async def start(self) -> "Stream":
        self._client = httpx.AsyncClient(timeout=None)
        self._cm = self._client.stream("GET", self.url, headers=self.headers)
        self._resp = await self._cm.__aenter__()
        assert self._resp.status_code == 200
        self._task = asyncio.create_task(self._pump())
        await asyncio.wait_for(self.opened.wait(), 5)
        return self

    async def _pump(self) -> None:
        frame: list[str] = []
        try:
            async for line in self._resp.aiter_lines():
                self.raw += line + "\n"
                if line == "":
                    if frame and frame[0].startswith(": open"):
                        self.opened.set()
                    else:
                        data = [ln[6:] for ln in frame if ln.startswith("data: ")]
                        if data:
                            self.events.append(json.loads(data[0]))
                    frame = []
                else:
                    frame.append(line)
        except (httpx.HTTPError, asyncio.CancelledError):
            pass

    async def close(self) -> None:
        self._task.cancel()
        await self._cm.__aexit__(None, None, None)
        await self._client.aclose()


async def make(http: AsyncClient, who: dict[str, str], name: str = "Ada", **extra: object) -> dict:
    body = {"name": name, "salary": 5000, "notes": "likes tea", **extra}
    response = await http.post("/employees", json=body, headers=who)
    assert response.status_code == 201, response.text
    return response.json()


def pdf_text(content: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(content)).pages)


# --- 1. HEAD and DELETE follow the entity's access ------------------------------------------------------


async def test_head_and_delete_follow_the_entity_access(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["a_hr"], "Probe")
    url = f"/employees/{row['id']}"
    assert (await http.head(url)).status_code == 401  # anonymous: no existence probe
    assert (await http.delete(url)).status_code == 401
    assert (await http.head(url, headers=people["nobody"])).status_code == 403  # no role at all
    assert (await http.delete(url, headers=people["nobody"])).status_code == 403
    assert (await http.head(url, headers=people["b_hr"])).status_code == 404  # another tenant: absent
    assert (await http.delete(url, headers=people["b_hr"])).status_code == 404
    assert (await http.head(url, headers=people["a_staff"])).status_code == 200  # same tenant: fine
    assert (await http.get(url, headers=people["a_hr"])).status_code == 200  # the cross-tenant DELETE changed nothing
    assert (await http.delete(url, headers=people["a_staff"])).status_code == 204
    assert (await http.head(url, headers=people["a_staff"])).status_code == 404


# --- 2. a role without field access never sees the guarded field -----------------------------------------


async def test_transition_responses_hide_guarded_fields(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["a_hr"], "Mover", salary=SECRET_SALARY, notes=SECRET_NOTE)
    staff = people["a_staff"]
    listed = await http.get(f"/employees/{row['id']}/transitions", headers=staff)
    moved = await http.post(f"/employees/{row['id']}/transitions/archive", headers=staff)
    refused = await http.post(f"/employees/{row['id']}/transitions/approve", headers=staff)
    state_log = await http.get(f"/employees/{row['id']}/state-history", headers=staff)
    assert moved.status_code == 200 and moved.json()["status"] == "archived"
    assert "salary" not in moved.json() and "notes" not in moved.json()
    assert refused.status_code in (403, 409)
    for response in (listed, moved, refused, state_log):
        assert str(SECRET_SALARY) not in response.text and SECRET_NOTE not in response.text, response.text
    # hr moving a different row sees its own values
    other = await make(http, people["a_hr"], "Other", salary=SECRET_SALARY)
    hr_moved = await http.post(f"/employees/{other['id']}/transitions/archive", headers=people["a_hr"])
    assert hr_moved.status_code == 200 and hr_moved.json()["salary"] == SECRET_SALARY


async def test_documents_never_print_guarded_fields(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["a_hr"], "Cardholder", salary=SECRET_SALARY, notes=SECRET_NOTE)
    url = f"/documents/employee_card/records/{row['id']}"
    staff_pdf = await http.post(url, json={}, headers=people["a_staff"])
    assert staff_pdf.status_code == 200, staff_pdf.text
    text = pdf_text(staff_pdf.content)
    assert "Cardholder" in text and str(SECRET_SALARY) not in text and SECRET_NOTE not in text
    hr_text = pdf_text((await http.post(url, json={}, headers=people["a_hr"])).content)
    assert str(SECRET_SALARY) in hr_text and SECRET_NOTE in hr_text
    assert (await http.post(url, json={}, headers=people["b_hr"])).status_code == 404  # another tenant's record


async def test_history_never_reveals_guarded_values(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["a_hr"], "Historic", salary=SECRET_SALARY, notes=SECRET_NOTE)
    patched = await http.patch(
        f"/employees/{row['id']}",
        json={"name": "Renamed", "salary": SECRET_SALARY + 1, "notes": SECRET_NOTE + "-2"},
        headers=people["a_hr"],
    )
    assert patched.status_code == 200, patched.text
    url = f"/employees/{row['id']}/history"
    hr = await http.get(url, headers=people["a_hr"])
    assert hr.status_code == 200 and {"salary", "notes", "name"} <= {c["field"] for c in hr.json()}
    staff = await http.get(url, headers=people["a_staff"])
    assert staff.status_code == 200 and {c["field"] for c in staff.json()} == {"name"}
    assert "NOTESECRET" not in staff.text and "765432" not in staff.text
    assert (await http.get(url, headers=people["b_hr"])).status_code == 404


# --- 3. tenant isolation: realtime, search, metrics -----------------------------------------------------


async def test_realtime_is_tenant_scoped(http, people, server) -> None:  # noqa: ANN001
    a = await Stream(server, people["a_hr"]).start()
    b = await Stream(server, people["b_hr"]).start()
    try:
        mine = await make(http, people["a_hr"], "Alpha")
        theirs = await make(http, people["b_hr"], "Beta")
        await asyncio.sleep(2.5)
        assert [e["data"]["record_id"] for e in a.events] == [mine["id"]]
        assert [e["data"]["record_id"] for e in b.events] == [theirs["id"]]
        assert theirs["id"] not in a.raw and mine["id"] not in b.raw
    finally:
        await a.close()
        await b.close()


async def test_search_is_tenant_scoped_and_hides_guarded_fields(http, people) -> None:  # noqa: ANN001
    await make(http, people["a_hr"], "Zebracorn Alpha", notes="alphanote")
    await make(http, people["b_hr"], "Zebracorn Beta", notes="betanote")
    a = await http.get("/employees/search", params={"q": "zebracorn"}, headers=people["a_hr"])
    b = await http.get("/employees/search", params={"q": "zebracorn"}, headers=people["b_hr"])
    assert [i["name"] for i in a.json()["items"]] == ["Zebracorn Alpha"] and a.json()["total"] == 1
    assert [i["name"] for i in b.json()["items"]] == ["Zebracorn Beta"] and b.json()["total"] == 1
    # a tenant never finds the other tenant's note text, and staff cannot search a guarded field at all
    assert (await http.get("/employees/search", params={"q": "betanote"}, headers=people["a_hr"])).json()["total"] == 0
    assert (await http.get("/employees/search", params={"q": "alphanote"}, headers=people["a_staff"])).json()["total"] == 0
    assert "notes" not in (await http.get("/employees/search", params={"q": "zebracorn"}, headers=people["a_staff"])).text


async def test_metrics_are_tenant_scoped(http, people) -> None:  # noqa: ANN001
    await make(http, people["a_hr"], "A1", salary=100)
    await make(http, people["a_hr"], "A2", salary=200)
    await make(http, people["b_hr"], "B1", salary=1000000)
    count = (await http.get("/metrics/employee_count", headers=people["a_hr"])).json()
    assert count["value"] == 2
    assert (await http.get("/metrics/employee_count", headers=people["b_hr"])).json()["value"] == 1
    assert str((await http.get("/metrics/salary_total", headers=people["a_hr"])).json()["value"]) == "300"
    assert str((await http.get("/metrics/salary_total", headers=people["b_hr"])).json()["value"]) == "1000000"
    groups = (await http.get("/metrics/employee_by_status", headers=people["a_hr"])).json()["groups"]
    assert groups == [{"key": "draft", "value": 2}]
    # staff cannot read salary: refused, not an aggregate of hidden values
    assert (await http.get("/metrics/salary_total", headers=people["a_staff"])).status_code == 403
    assert (await http.get("/metrics/employee_count", headers=people["a_staff"])).json()["value"] == 2
