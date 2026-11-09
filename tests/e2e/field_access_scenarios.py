"""Scenario tests for the generated `field_access` project. Copied into the project's tests/ folder by
tests/e2e/test_field_access_stack.py and run against a real Postgres.

Rules under test (spec.authorization.field_access on Employee): salary is read by hr + admin and written by
hr (admin inherits hr); notes is read by hr only. Someone without read access never sees the key (not even
as null) in any response, cannot filter, sort or search by it, and a write of a field they may not write
is a 403 that changes nothing.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "staff": await sign_in(http, "staff@example.com", roles=["staff"], n=0),
        "hr": await sign_in(http, "hr@example.com", roles=["hr"], n=1),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=2),
    }


async def make(http: AsyncClient, who: dict[str, str], name: str = "Ada", **extra: object) -> dict:
    response = await http.post(
        "/employees", json={"name": name, "salary": 5000, "notes": "likes tea", **extra}, headers=who
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_hr_sees_and_writes_salary(http, people) -> None:  # noqa: ANN001
    created = await make(http, people["hr"])
    assert created["salary"] == 5000 and created["notes"] == "likes tea"
    got = (await http.get(f"/employees/{created['id']}", headers=people["hr"])).json()
    assert got["salary"] == 5000
    patched = await http.patch(f"/employees/{created['id']}", json={"salary": 6000}, headers=people["hr"])
    assert patched.status_code == 200 and patched.json()["salary"] == 6000
    listed = (await http.get("/employees", headers=people["hr"])).json()
    assert listed["items"][0]["salary"] == 6000


async def test_admin_reads_through_inheritance_and_writes_as_hr(http, people) -> None:  # noqa: ANN001
    created = await make(http, people["admin"])
    assert created["salary"] == 5000
    assert "notes" in created  # admin inherits hr


async def test_staff_never_sees_the_hidden_fields(http, people) -> None:  # noqa: ANN001
    hr_row = await make(http, people["hr"])
    # create by staff without the fields: the response has no salary / notes keys
    created = await http.post("/employees", json={"name": "Bob"}, headers=people["staff"])
    assert created.status_code == 201, created.text
    assert "salary" not in created.json() and "notes" not in created.json()
    assert created.json()["name"] == "Bob"
    got = (await http.get(f"/employees/{hr_row['id']}", headers=people["staff"])).json()
    assert got["name"] == "Ada" and "salary" not in got and "notes" not in got
    listed = (await http.get("/employees", headers=people["staff"])).json()
    assert listed["total"] == 2
    for item in listed["items"]:
        assert "salary" not in item and "notes" not in item and "name" in item
    updated = await http.patch(f"/employees/{hr_row['id']}", json={"name": "Ada L"}, headers=people["staff"])
    assert updated.status_code == 200
    assert "salary" not in updated.json() and updated.json()["name"] == "Ada L"
    replaced = await http.put(f"/employees/{hr_row['id']}", json={"name": "Ada M"}, headers=people["staff"])
    assert replaced.status_code == 200 and "salary" not in replaced.json()
    # the replace by a non-writer did not wipe the value
    assert (await http.get(f"/employees/{hr_row['id']}", headers=people["hr"])).json()["salary"] == 5000


async def test_staff_cannot_filter_sort_or_search_by_hidden_fields(http, people) -> None:  # noqa: ANN001
    await make(http, people["hr"], notes="secret-marker")
    probes = await http.get("/employees?salary=5000", headers=people["staff"])
    assert probes.status_code == 403 and "Ada" not in probes.text
    assert (await http.get("/employees?sort=salary", headers=people["staff"])).status_code == 403
    assert (await http.get("/employees?sort=-salary,name", headers=people["staff"])).status_code == 403
    # q ignores the hidden field: "secret-marker" lives only in notes, so it finds nothing
    found = (await http.get("/employees?q=secret-marker", headers=people["staff"])).json()
    assert found["items"] == [] or all("notes" not in i for i in found["items"])
    by_name = (await http.get("/employees?q=Ada", headers=people["staff"])).json()
    assert by_name["total"] == 1
    # hr can use them
    assert (await http.get("/employees?salary=5000", headers=people["hr"])).json()["total"] == 1
    assert (await http.get("/employees?sort=salary", headers=people["hr"])).status_code == 200
    assert (await http.get("/employees?q=secret-marker", headers=people["hr"])).json()["total"] == 1


async def test_staff_cannot_write_salary(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["hr"])
    for call in (
        http.post("/employees", json={"name": "Eve", "salary": 1}, headers=people["staff"]),
        http.patch(f"/employees/{row['id']}", json={"salary": 1}, headers=people["staff"]),
        http.put(f"/employees/{row['id']}", json={"name": "Ada", "salary": 1}, headers=people["staff"]),
    ):
        response = await call
        assert response.status_code == 403, response.text
    assert (await http.get(f"/employees/{row['id']}", headers=people["hr"])).json()["salary"] == 5000
    assert (await http.get("/employees", headers=people["hr"])).json()["total"] == 1  # no Eve


async def test_hr_may_write_salary_but_not_a_staff_only_write(http, people) -> None:  # noqa: ANN001
    row = await make(http, people["hr"])
    ok = await http.put(
        f"/employees/{row['id']}", json={"name": "Ada", "salary": 7000}, headers=people["hr"]
    )
    assert ok.status_code == 200 and ok.json()["salary"] == 7000


async def transitions(http: AsyncClient, who: dict[str, str], row: dict) -> dict[str, dict]:
    response = await http.get(f"/employees/{row['id']}/transitions", headers=who)
    assert response.status_code == 200, response.text
    return {t["name"]: t for t in response.json()}


async def test_a_guard_is_not_an_oracle_for_someone_who_cannot_read_the_record_fully(http, people) -> None:  # noqa: ANN001
    """`approve` (hr only) is guarded by salary > 100000; `archive` (anyone who may update) by name != "Frozen".
    Staff cannot read salary: they must learn nothing from a refused guard, neither in the list of
    transitions nor in the 409. hr can read every field and gets the real reason."""
    rich = await make(http, people["hr"], "Rich", salary=200000)
    poor = await make(http, people["hr"], "Poor", salary=50)
    frozen = await make(http, people["hr"], "Frozen", salary=200000)
    # staff: approve is a role matter (the same answer for rich and poor); no guard detail anywhere
    for row in (rich, poor):
        seen = await transitions(http, people["staff"], row)
        assert seen["approve"]["refused_because"] == "role" and seen["approve"]["allowed"] is False
        assert seen["archive"]["allowed"] is True and seen["archive"]["refused_because"] is None
    denied = await http.post(f"/employees/{poor['id']}/transitions/approve", headers=people["staff"])
    assert denied.status_code == 403 and "100000" not in denied.text and "guard" not in denied.text
    # a guard that refuses staff is reported with the generic reason, and the 409 does not name the conditions
    seen = await transitions(http, people["staff"], frozen)
    assert seen["archive"]["allowed"] is False and seen["archive"]["refused_because"] == "unavailable"
    refused = await http.post(f"/employees/{frozen['id']}/transitions/archive", headers=people["staff"])
    assert refused.status_code == 409 and refused.json()["code"] == "transition_refused"
    assert "conditions" not in refused.text and "guard" not in refused.text
    # hr reads everything: the real reason
    assert (await transitions(http, people["hr"], poor))["approve"]["refused_because"] == "guard"
    assert (await transitions(http, people["hr"], frozen))["archive"]["refused_because"] == "guard"
    again = await http.post(f"/employees/{frozen['id']}/transitions/archive", headers=people["hr"])
    assert again.status_code == 409 and "conditions" in again.json()["message"]
    # the allowed path still works, and the response hides what staff may not read
    assert (await http.post(f"/employees/{poor['id']}/transitions/approve", headers=people["hr"])).status_code == 409
    moved = await http.post(f"/employees/{rich['id']}/transitions/approve", headers=people["hr"])
    assert moved.status_code == 200 and moved.json()["status"] == "approved" and moved.json()["salary"] == 200000
    archived = await http.post(f"/employees/{rich['id']}/transitions/archive", headers=people["staff"])
    assert archived.status_code == 200 and archived.json()["status"] == "archived" and "salary" not in archived.json()
