"""CP4F2-B: import fixes: duplicate re-check on fix, commit charges inserted rows only, C7 on reads,
CSV export neutralization, review-queue paging."""

import copy
import csv
import io
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_data_import import project_with_contact, upload
from tests.unit.test_access_layers import base

GOOD = b"Full Name,Email,Age\nAnn,ann@x.io,30\nCy,cy@x.io,41\n"


async def _commit(client: AsyncClient, pid: str, bid: str) -> Any:
    return await client.post(f"/projects/{pid}/imports/{bid}/commit")


async def test_fix_into_duplicate_and_back(client: AsyncClient) -> None:
    pid = await project_with_contact(client)
    csv_data = b"Full Name,Email,Age\nAnn,ann@x.io,30\nBob,ann@x.io,zz\nCy,cy@x.io,41\n"
    prev = (await upload(client, pid, csv_data)).json()
    bid = prev["batch_id"]
    assert prev["counts"]["rejected"] == 1
    rows = (await client.get(f"/projects/{pid}/imports/{bid}/rows")).json()["items"]
    bad = next(r for r in rows if r["status"] == "rejected")
    plain = next(r for r in rows if r["status"] == "accepted")
    # the fix makes the key collide with the accepted row of the same batch -> duplicate
    r = await client.put(f"/projects/{pid}/imports/{bid}/rows/{bad['id']}", json={"values": {"age": 31}})
    assert r.status_code == 200 and r.json()["status"] == "duplicate", r.text
    c = (await client.get(f"/projects/{pid}/imports/{bid}")).json()["counts"]
    assert (c["rejected"], c["duplicate"], c["fixed"], c["accepted"]) == (0, 1, 0, 2)
    # a duplicate produced by a fix can be fixed again, a plain accepted row cannot
    r = await client.put(
        f"/projects/{pid}/imports/{bid}/rows/{bad['id']}", json={"values": {"age": 31, "email": "new@x.io"}}
    )
    assert r.json()["status"] == "fixed", r.text
    c = (await client.get(f"/projects/{pid}/imports/{bid}")).json()["counts"]
    assert (c["duplicate"], c["fixed"]) == (0, 1)
    r = await client.put(f"/projects/{pid}/imports/{bid}/rows/{plain['id']}", json={"values": {"age": 1}})
    assert r.status_code == 409 and r.json()["code"] == "import_row_not_fixable"
    res = (await _commit(client, pid, bid)).json()
    assert res["created"] == 3


async def test_fix_collides_with_committed_record(client: AsyncClient) -> None:
    pid = await project_with_contact(client)
    first = (await upload(client, pid, GOOD)).json()["batch_id"]
    assert (await _commit(client, pid, first)).json()["created"] == 2
    second = (await upload(client, pid, b"Full Name,Email,Age\nAnn,ann@x.io,xx\n")).json()["batch_id"]
    row = (await client.get(f"/projects/{pid}/imports/{second}/rows")).json()["items"][0]
    r = await client.put(f"/projects/{pid}/imports/{second}/rows/{row['id']}", json={"values": {"age": 5}})
    assert r.json()["status"] == "duplicate"
    res = (await _commit(client, pid, second)).json()
    assert (res["created"], res["duplicate"]) == (0, 1)


async def test_commit_charges_only_inserted_rows(client: AsyncClient) -> None:
    pid = await project_with_contact(client)
    slug = (await client.get("/orgs")).json()["items"][0]["slug"]
    r = await client.put(f"/orgs/{slug}/usage/limits/imports.rows", json={"limit_value": 3})
    assert r.status_code == 200, r.text
    b1 = (await upload(client, pid, GOOD)).json()["batch_id"]
    assert (await _commit(client, pid, b1)).json()["created"] == 2
    # all duplicates: charges nothing even though only 1 unit is left
    b2 = (await upload(client, pid, GOOD + b"")).json()["batch_id"]
    res = await _commit(client, pid, b2)
    assert res.status_code == 200 and res.json()["created"] == 0 and res.json()["duplicate"] == 2
    # one duplicate + one new row: charged 1 (total 3)
    b3 = (await upload(client, pid, b"Full Name,Email,Age\nAnn,ann@x.io,30\nDee,dee@x.io,5\n")).json()["batch_id"]
    res = await _commit(client, pid, b3)
    assert res.status_code == 200 and res.json()["created"] == 1
    # the next new row is over quota: 429, nothing stored, batch still committable later
    b4 = (await upload(client, pid, b"Full Name,Email,Age\nEve,eve@x.io,9\n")).json()["batch_id"]
    res = await _commit(client, pid, b4)
    assert res.status_code == 429 and "quota_exceeded" in res.text
    assert (await client.get(f"/projects/{pid}/imports/records?entity=Contact")).json()["total"] == 3
    assert (await client.get(f"/projects/{pid}/imports/{b4}")).json()["status"] == "previewed"


# -- C7 + export ------------------------------------------------------------------------------


def _spec() -> dict[str, Any]:
    raw = copy.deepcopy(base())
    raw["auth"]["roles"] = [
        {"name": "admin", "label": "Admin"},
        {"name": "owner", "label": "Owner"},
        {"name": "editor", "label": "Editor"},
        {"name": "viewer", "label": "Viewer", "is_default": True},
    ]
    raw["auth"]["permissions"] = []
    raw["authorization"]["field_access"] = [
        {"entity": "Person", "field": "salary", "read_roles": ["owner", "editor"], "write_roles": ["owner"]}
    ]
    return raw


PEOPLE = b'name,notes,salary\nAnn,"=HYPERLINK(""x"")",100\nBob,hi,200\n'


async def _setup(client: AsyncClient, client_for: ClientFor) -> tuple[str, str, AsyncClient, AsyncClient]:
    pid = await make_project(client, "People")
    raw = _spec()
    raw["project"] = {"name": "People", "slug": "people", "description": None, "db_engine": "postgres"}
    r = await client.put(f"/projects/{pid}/spec", json=raw)
    assert r.status_code == 200, r.text
    prev = await upload(client, pid, PEOPLE, entity="Person")
    assert prev.status_code == 201, prev.text
    bid = prev.json()["batch_id"]
    clients = []
    for email, role in (("vi@example.com", "viewer"), ("ed@example.com", "editor")):
        clients.append(await client_for(email))
        await add_to_project_org(pid, email)
        m = await client.post(f"/projects/{pid}/members", json={"email": email, "role": role})
        assert m.status_code == 201, m.text
    assert (await _commit(client, pid, bid)).status_code == 200
    return pid, bid, clients[0], clients[1]


async def test_c7_records_and_rows_hide_guarded_fields(client: AsyncClient, client_for: ClientFor) -> None:
    pid, bid, viewer, editor = await _setup(client, client_for)
    for c, sees in ((client, True), (editor, True), (viewer, False)):
        recs = (await c.get(f"/projects/{pid}/imports/records?entity=Person")).json()
        assert recs["total"] == 2
        assert all(("salary" in i["data"]) is sees for i in recs["items"]), sees
        assert all("name" in i["data"] for i in recs["items"])
        rows = (await c.get(f"/projects/{pid}/imports/{bid}/rows")).json()["items"]
        assert all(("salary" in (r["record"] or {})) is sees for r in rows)
        assert all(("salary" in r["raw"]) is sees for r in rows)
        pv = (await c.get(f"/projects/{pid}/imports/{bid}")).json()
        assert all(("salary" in (r["record"] or {})) is sees for r in pv["sample"])
    assert "200" not in (await viewer.get(f"/projects/{pid}/imports/{bid}/rows")).text


async def test_export_csv_neutralizes_and_hides(client: AsyncClient, client_for: ClientFor) -> None:
    pid, _, viewer, _ = await _setup(client, client_for)
    r = await viewer.get(f"/projects/{pid}/imports/records/export.csv?entity=Person")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-export-truncated"] == "false"
    table = list(csv.reader(io.StringIO(r.text)))
    assert table[0] == ["name", "notes"]
    assert "salary" not in r.text and "200" not in r.text
    assert any(row[1] == "'=HYPERLINK(\"x\")" for row in table[1:])
    full = (await client.get(f"/projects/{pid}/imports/records/export.csv?entity=Person")).text
    assert "salary" in full.splitlines()[0]
    assert (await client.get(f"/projects/{pid}/imports/records/export.csv?entity=Nope")).status_code == 400


async def test_review_queue_paging_over_100_rows(client: AsyncClient) -> None:
    pid = await project_with_contact(client)
    body = "Full Name,Email,Age\n" + "".join(f",e{i}@x.io,1\n" for i in range(130))
    body += "Ok,ok@x.io,3\n"
    bid = (await upload(client, pid, body.encode())).json()["batch_id"]
    p = (await client.get(f"/projects/{pid}/imports/{bid}/rows?status=rejected&limit=100&offset=100")).json()
    assert p["total"] == 130 and len(p["items"]) == 30
    assert all(i["status"] == "rejected" for i in p["items"])
    assert p["items"][0]["row_no"] == 101
    allrows = (await client.get(f"/projects/{pid}/imports/{bid}/rows?limit=500")).json()
    assert allrows["total"] == 131 and len(allrows["items"]) == 131
    acc = (await client.get(f"/projects/{pid}/imports/{bid}/rows?status=accepted")).json()
    assert acc["total"] == 1
