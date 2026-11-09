"""B4-3: search over a project's imported records returns only what the chosen role may read."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor
from tests.unit.test_access_layers import base

CSV = b"Name,Notes,Salary\nAnna Berg,loves chess,9100\nBen Hall,plays chess,8200\nCleo Fox,hiking,7300\n"


async def seeded(client: AsyncClient, *, row_rule: str | None) -> str:
    pid = await make_project(client, "People")
    raw = base()
    raw["project"] = {"name": "People", "slug": "people", "description": None, "db_engine": "postgres"}
    for p in raw["auth"]["permissions"]:
        if p["operation"] == "list":
            if row_rule is None:
                p.pop("row_rule", None)
            else:
                p["row_rule"] = row_rule
    assert (await client.put(f"/projects/{pid}/spec", json=raw)).status_code == 200
    up = await client.post(
        f"/projects/{pid}/imports", files={"file": ("p.csv", CSV, "text/csv")}, data={"entity": "Person"}
    )
    assert up.status_code == 201, up.text
    c = await client.post(f"/projects/{pid}/imports/{up.json()['batch_id']}/commit")
    assert c.status_code == 200 and c.json()["created"] == 3, c.text
    return pid


async def find(client: AsyncClient, pid: str, q: str, role: str | None, adapter: str = "fts") -> dict:
    params = {"entity": "Person", "q": q, "adapter": adapter}
    if role:
        params["as_role"] = role
    r = await client.get(f"/projects/{pid}/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_each_role_sees_only_what_it_may_read(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    pid = await seeded(client, row_rule=None)
    # staff can list Person but not read salary: a salary value finds nothing and no hit shows it
    assert (await find(client, pid, "9100", "staff"))["total"] == 0
    hits = await find(client, pid, "chess", "staff")
    assert hits["total"] == 2 and all("salary" not in h for h in hits["hits"])
    assert {h["name"] for h in hits["hits"]} == {"Anna Berg", "Ben Hall"}
    # hr may read salary: the value matches and is returned
    hr = await find(client, pid, "9100", "hr")
    assert hr["total"] == 1 and hr["hits"][0]["salary"] == "9100"
    # not signed in: nothing
    assert (await find(client, pid, "chess", None))["total"] == 0


async def test_row_rule_hides_rows_from_hits_and_counts(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    pid = await seeded(client, row_rule="role_scoped")
    # role_scoped = own rows only, admins all; imported rows have no creator, so staff sees none
    staff = await find(client, pid, "chess", "staff")
    assert staff["total"] == 0 and staff["hits"] == []
    admin = await find(client, pid, "chess", "admin")
    assert admin["total"] == 2


async def test_adapter_swap_gives_the_same_filtered_set(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    pid = await seeded(client, row_rule=None)
    for role in ("staff", "hr", "admin"):
        a = await find(client, pid, "chess", role, "fts")
        b = await find(client, pid, "chess", role, "opensearch")
        assert {h["id"] for h in a["hits"]} == {h["id"] for h in b["hits"]}
        assert a["total"] == b["total"]


async def test_bad_inputs_are_refused(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    pid = await seeded(client, row_rule=None)
    base_q = {"entity": "Person", "q": "x"}
    assert (await client.get(f"/projects/{pid}/search", params={**base_q, "as_role": "nope"})).status_code == 422
    assert (await client.get(f"/projects/{pid}/search", params={**base_q, "adapter": "x"})).status_code == 422
    assert (await client.get(f"/projects/{pid}/search", params={**base_q, "entity": "Nope"})).status_code == 404
    other = await client_for("b@example.com")
    assert (await other.get(f"/projects/{pid}/search", params=base_q)).status_code in (403, 404)
