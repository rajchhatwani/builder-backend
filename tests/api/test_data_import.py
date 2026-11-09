"""B4-1: CSV import over the API: preview before commit, review queue, idempotent and race-safe commit."""

import asyncio
import json
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.data_import import ImportedRecord
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

CSV = b"Full Name,Email,Age\nAnn,ann@x.io,30\nBob,bob@x.io,not-a-number\nCy,cy@x.io,41\n"


async def project_with_contact(client: AsyncClient) -> str:
    pid = await make_project(client, "People")
    raw = {
        "spec_version": 1,
        "project": {"name": "People", "slug": "people", "description": None, "db_engine": "postgres"},
        "entities": [
            {
                "name": "Contact",
                "table_name": "contacts",
                "plural_path": "contacts",
                "options": {},
                "fields": [
                    {"name": "full_name", "type": "string", "required": True, "max_length": 50},
                    {"name": "email", "type": "string", "unique": True},
                    {"name": "age", "type": "integer", "min_value": 0, "max_value": 120},
                ],
            }
        ],
        "relations": [],
    }
    r = await client.put(f"/projects/{pid}/spec", json=raw)
    assert r.status_code == 200, r.text
    return pid


async def upload(
    client: AsyncClient, pid: str, data: bytes = CSV, entity: str = "Contact", mapping: Any = None
) -> Any:
    form = {"entity": entity}
    if mapping is not None:
        form["mapping"] = json.dumps(mapping)
    return await client.post(
        f"/projects/{pid}/imports", files={"file": ("people.csv", data, "text/csv")}, data=form
    )


async def n_records(sf: async_sessionmaker[AsyncSession]) -> int:
    async with sf() as s:
        return (await s.execute(select(func.count()).select_from(ImportedRecord))).scalar_one()


async def test_preview_then_commit_and_review_queue(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await project_with_contact(client)
    r = await upload(client, pid)
    assert r.status_code == 201, r.text
    prev = r.json()
    assert prev["counts"]["total"] == 3 and prev["counts"]["accepted"] == 2 and prev["counts"]["rejected"] == 1
    assert prev["suggested_mapping"] == {"full_name": "Full Name", "email": "Email", "age": "Age"}
    assert len(prev["sample"]) == 3 and len(prev["rejected"]) == 1
    assert prev["rejected"][0]["row_no"] == 2
    assert prev["rejected"][0]["errors"][0]["field"] == "age"
    assert await n_records(session_factory) == 0  # nothing written before commit

    bid = prev["batch_id"]
    c = await client.post(f"/projects/{pid}/imports/{bid}/commit")
    assert c.status_code == 200, c.text
    assert (c.json()["created"], c.json()["duplicate"], c.json()["rejected"]) == (2, 0, 1)
    assert await n_records(session_factory) == 2
    q = (await client.get(f"/projects/{pid}/imports/{bid}/rows?status=rejected")).json()
    assert q["total"] == 1 and q["items"][0]["raw"]["Full Name"] == "Bob"
    recs = (await client.get(f"/projects/{pid}/imports/records?entity=Contact")).json()
    assert recs["total"] == 2 and {r["data"]["email"] for r in recs["items"]} == {"ann@x.io", "cy@x.io"}
    # idempotent
    again = await client.post(f"/projects/{pid}/imports/{bid}/commit")
    assert again.json() == c.json() and await n_records(session_factory) == 2
    assert (await client.get(f"/projects/{pid}/imports/{bid}")).json()["status"] == "committed"


async def test_second_import_duplicates_and_fix_adds_one(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await project_with_contact(client)
    first = (await upload(client, pid)).json()
    await client.post(f"/projects/{pid}/imports/{first['batch_id']}/commit")
    second = (await upload(client, pid)).json()
    assert second["counts"]["duplicate"] == 2 and second["counts"]["accepted"] == 0
    done = (await client.post(f"/projects/{pid}/imports/{second['batch_id']}/commit")).json()
    assert (done["created"], done["duplicate"]) == (0, 2)
    assert await n_records(session_factory) == 2

    third = (await upload(client, pid)).json()
    bad_id = third["rejected"][0]["id"]
    url = f"/projects/{pid}/imports/{third['batch_id']}/rows/{bad_id}"
    still = (await client.put(url, json={"values": {"age": "still bad"}})).json()
    assert still["status"] == "rejected" and still["errors"][0]["code"] == "invalid_integer"
    fixed = (await client.put(url, json={"values": {"age": "25"}})).json()
    assert fixed["status"] == "fixed" and fixed["record"]["age"] == 25 and fixed["errors"] == []
    res = (await client.post(f"/projects/{pid}/imports/{third['batch_id']}/commit")).json()
    assert res["created"] == 1 and res["duplicate"] == 2 and res["rejected"] == 0
    assert await n_records(session_factory) == 3
    r = await client.put(url, json={"values": {"age": "26"}})
    assert r.status_code == 409 and r.json()["code"] == "import_not_previewed"


async def test_mapping_revalidates_whole_batch(client: AsyncClient) -> None:
    pid = await project_with_contact(client)
    data = b"who,mail,years\nAnn,a@x.io,3\nBob,b@x.io,4\n"
    prev = (await upload(client, pid, data)).json()
    assert prev["counts"]["rejected"] == 2 and prev["mapping"] == {}  # nothing matched by name
    r = await client.put(
        f"/projects/{pid}/imports/{prev['batch_id']}/mapping",
        json={"mapping": {"full_name": "who", "email": "mail", "age": "years"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["accepted"] == 2 and r.json()["counts"]["rejected"] == 0
    bad = await client.put(
        f"/projects/{pid}/imports/{prev['batch_id']}/mapping", json={"mapping": {"age": "nope"}}
    )
    assert bad.status_code == 400 and bad.json()["code"] == "import_bad_mapping"
    # cancel blocks commit
    assert (await client.post(f"/projects/{pid}/imports/{prev['batch_id']}/cancel")).json()["status"] == "cancelled"
    c = await client.post(f"/projects/{pid}/imports/{prev['batch_id']}/commit")
    assert c.status_code == 409 and c.json()["code"] == "import_not_previewed"


async def test_roles_and_isolation(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await project_with_contact(client)
    prev = (await upload(client, pid)).json()
    bid = prev["batch_id"]
    await add_to_project_org(pid, "vi@example.com")
    vi = await client_for("vi@example.com")
    await add_to_project_org(pid, "vi@example.com")
    r = await client.post(f"/projects/{pid}/members", json={"email": "vi@example.com", "role": "viewer"})
    assert r.status_code == 201
    assert (await upload(vi, pid)).status_code == 403
    assert (await vi.post(f"/projects/{pid}/imports/{bid}/commit")).status_code == 403
    assert (await vi.get(f"/projects/{pid}/imports/{bid}")).status_code == 200
    assert (await vi.get(f"/projects/{pid}/imports/{bid}/rows")).status_code == 200
    eve = await client_for("eve@example.com")
    assert (await eve.get(f"/projects/{pid}/imports/{bid}")).status_code == 404
    assert (await upload(eve, pid)).status_code == 404
    # another project of the same owner cannot reach the batch by id
    other = await make_project(client, "Other")
    assert (await client.get(f"/projects/{other}/imports/{bid}")).status_code == 404


async def test_stable_error_codes(client: AsyncClient) -> None:
    pid = await project_with_contact(client)
    r = await upload(client, pid, b"a\n" + b"x" * (5 * 1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["code"] == "import_too_large"
    r = await upload(client, pid, b"a,a\n1,2\n")
    assert r.status_code == 400 and r.json()["code"] == "import_bad_csv"
    r = await upload(client, pid, b"\xff\xfe\x00")
    assert r.json()["code"] == "import_bad_csv"
    r = await upload(client, pid, CSV, entity="Nope")
    assert r.status_code == 400 and r.json()["code"] == "import_unknown_entity"
    rows = "a\n" + "\n".join(["1"] * 20_001) + "\n"
    r = await upload(client, pid, rows.encode())
    assert r.status_code == 413 and r.json()["code"] == "import_too_large"


async def test_parallel_commits_insert_once(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await project_with_contact(client)
    bid = (await upload(client, pid)).json()["batch_id"]
    rs = await asyncio.gather(*[client.post(f"/projects/{pid}/imports/{bid}/commit") for _ in range(6)])
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    assert {(r.json()["created"], r.json()["duplicate"]) for r in rs} == {(2, 0)}
    assert await n_records(session_factory) == 2


async def test_commit_is_metered_and_refused_over_quota(client: AsyncClient) -> None:
    """CP-4D wiring: commit charges imports.rows; a limit of 1 refuses a 2-row commit."""
    pid = await project_with_contact(client)
    slug = (await client.get("/orgs")).json()["items"][0]["slug"]
    r = await client.put(f"/orgs/{slug}/usage/limits/imports.rows", json={"limit_value": 1})
    assert r.status_code == 200, r.text
    bid = (await upload(client, pid)).json()["batch_id"]
    c = await client.post(f"/projects/{pid}/imports/{bid}/commit")
    assert c.status_code == 429 and "quota_exceeded" in c.text, c.text
    recs = (await client.get(f"/projects/{pid}/imports/records?entity=Contact")).json()
    assert recs["total"] == 0
