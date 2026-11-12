"""CP4F4-B: import C7 hardening (L1 raw/headers by name, L2 fix_row access + no existence oracle) and
the upload body cap (L8)."""

import copy
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_data_import import upload
from tests.unit.test_access_layers import base


async def _setup(client: AsyncClient, client_for: ClientFor) -> tuple[str, AsyncClient]:
    """Owner project where only `owner` may read/write Person.salary; returns (project, editor client)."""
    pid = await make_project(client, "People")
    raw: dict[str, Any] = copy.deepcopy(base())
    raw["auth"]["roles"] = [
        {"name": "admin", "label": "Admin"},
        {"name": "owner", "label": "Owner"},
        {"name": "editor", "label": "Editor"},
        {"name": "viewer", "label": "Viewer", "is_default": True},
    ]
    raw["auth"]["permissions"] = []
    raw["authorization"]["field_access"] = [
        {"entity": "Person", "field": "salary", "read_roles": ["owner"], "write_roles": ["owner"]}
    ]
    raw["project"] = {"name": "People", "slug": "people", "description": None, "db_engine": "postgres"}
    r = await client.put(f"/projects/{pid}/spec", json=raw)
    assert r.status_code == 200, r.text
    editor = await client_for("ed4@example.com")
    await add_to_project_org(pid, "ed4@example.com")
    m = await client.post(f"/projects/{pid}/members", json={"email": "ed4@example.com", "role": "editor"})
    assert m.status_code == 201, m.text
    return pid, editor


async def test_l1_preview_strips_hidden_column_even_when_unmapped(
    client: AsyncClient, client_for: ClientFor
) -> None:
    pid, editor = await _setup(client, client_for)
    data = b"name,notes,SALARY\nAnn,hi,100\n"
    prev = await upload(client, pid, data, entity="Person", mapping={"salary": None})  # unmapped
    assert prev.status_code == 201, prev.text
    bid = prev.json()["batch_id"]
    owner_view = (await client.get(f"/projects/{pid}/imports/{bid}")).json()
    assert "SALARY" in owner_view["headers"] and "SALARY" in owner_view["sample"][0]["raw"]
    for url in (f"/projects/{pid}/imports/{bid}", f"/projects/{pid}/imports/{bid}/rows"):
        text = (await editor.get(url)).text
        assert "SALARY" not in text and "100" not in text and "salary" not in text.lower(), text
    pv = (await editor.get(f"/projects/{pid}/imports/{bid}")).json()
    assert pv["headers"] == ["name", "notes"] and "salary" not in pv["suggested_mapping"]
    # remapped later: the column is mapped to the hidden field, then unmapped again
    await client.put(f"/projects/{pid}/imports/{bid}/mapping", json={"mapping": {"salary": "SALARY"}})
    await client.put(f"/projects/{pid}/imports/{bid}/mapping", json={"mapping": {"salary": None}})
    assert "SALARY" not in (await editor.get(f"/projects/{pid}/imports/{bid}")).text


async def test_l2_fix_row_refuses_hidden_field_and_hides_key_existence(
    client: AsyncClient, client_for: ClientFor
) -> None:
    pid, editor = await _setup(client, client_for)
    first = (await upload(client, pid, b"name,notes,salary\nAnn,hi,100\n", entity="Person")).json()
    assert (await client.post(f"/projects/{pid}/imports/{first['batch_id']}/commit")).status_code == 200
    bid = (await upload(client, pid, b"name,notes,salary\n" + b"A" * 100 + b",hi,100\n", entity="Person")).json()[
        "batch_id"
    ]
    row = (await client.get(f"/projects/{pid}/imports/{bid}/rows")).json()["items"][0]
    assert row["status"] == "rejected"
    url = f"/projects/{pid}/imports/{bid}/rows/{row['id']}"
    denied = await editor.put(url, json={"values": {"salary": "5"}})
    assert denied.status_code == 403 and denied.json()["code"] == "field_access_denied"
    # the fix collides with the committed record whose key includes the hidden salary: generic rejection
    r = await editor.put(url, json={"values": {"name": "Ann"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected" and body["errors"][0]["code"] == "import_row_rejected"
    assert "duplicate" not in r.text and "already exists" not in r.text
    # the owner (who can read the key) still sees the real duplicate
    r = await client.put(url, json={"values": {"name": "Ann"}})
    assert r.json()["status"] == "duplicate"


async def test_l8_upload_over_cap_is_refused_before_parsing(client: AsyncClient) -> None:
    pid = await make_project(client, "Big")
    big = b"a,b\n" + b"x" * (5 * 1024 * 1024 + 300 * 1024)
    # declared Content-Length over the cap: 413 with the stable code, before the multipart is parsed
    r = await client.post(
        f"/projects/{pid}/imports",
        content=big,
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 413 and r.json()["code"] == "import_too_large", r.text
    # a small upload is unaffected
    ok = await client.post(
        f"/projects/{pid}/imports", files={"file": ("a.csv", b"a\n1\n", "text/csv")}, data={"entity": "Nope"}
    )
    assert ok.status_code == 400  # import_unknown_entity, i.e. it reached the handler
