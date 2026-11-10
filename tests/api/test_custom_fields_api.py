"""CP4F2-B: custom-field endpoints over the typed ops: define, list, promote-check, promote, roles."""

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "specs" / "custom_fields.json"


async def project(client: AsyncClient) -> str:
    pid = await make_project(client, "Contacts")
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    r = await client.put(f"/projects/{pid}/spec", json=raw)
    assert r.status_code == 200, r.text
    return pid


def url(pid: str, *rest: str, entity: str = "Contact") -> str:
    return "/".join([f"/projects/{pid}/entities/{entity}/custom-fields", *rest]).rstrip("/")


async def test_define_list_check_promote(client: AsyncClient) -> None:
    pid = await project(client)
    listed = (await client.get(url(pid))).json()
    assert listed["enabled"] is True and "score" in [d["name"] for d in listed["items"]]  # persisted from the PUT
    r = await client.post(url(pid), json={"name": "region", "type": "string", "max_length": 10})
    assert r.status_code == 201, r.text
    assert "region" in [d["name"] for d in (await client.get(url(pid))).json()["items"]]
    assert (await client.post(url(pid), json={"name": "region", "type": "string"})).status_code == 409
    bad = await client.post(url(pid), json={"name": "full_name", "type": "int"})
    assert bad.status_code == 422 and bad.json()["code"] == "spec_invalid"
    # patch
    r = await client.patch(url(pid, "region"), json={"max_length": 20})
    assert r.status_code == 200 and r.json()["max_length"] == 20
    # check: a sample that does not fit is reported with a stable code and writes nothing
    chk = await client.post(url(pid, "region", "promote-check"), json={"samples": ["ok", "x" * 21, None]})
    assert chk.status_code == 200, chk.text
    body = chk.json()
    assert body["ok"] is False
    assert [(p["code"], p["sample_index"]) for p in body["problems"] if p["severity"] == "error"] == [
        ("custom_field_promote_too_long", 1)
    ]
    assert body["plan_sql"] and "ALTER TABLE" in body["plan_sql"][0]
    assert "region" in [d["name"] for d in (await client.get(url(pid))).json()["items"]]
    good = (await client.post(url(pid, "region", "promote-check"), json={"samples": ["ok", "fine"]})).json()
    assert good["ok"] is True
    assert (await client.post(url(pid, "region", "promote-check"))).json()["ok"] is True  # samples optional
    # promote through the op
    r = await client.post(url(pid, "region", "promote"))
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["op_seq"] >= 1 and any(s["kind"] == "promote_custom_field" for s in res["migration_steps"])
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    contact = next(e for e in spec["entities"] if e["name"] == "Contact")
    assert any(f["name"] == "region" for f in contact["fields"])
    assert "region" not in [d["name"] for d in contact["custom_fields"]["defs"]]
    assert "region" not in [d["name"] for d in (await client.get(url(pid))).json()["items"]]
    ops = (await client.get(f"/projects/{pid}/spec/ops")).json()["items"]
    assert ops[0]["op_type"] == "promote_custom_field" and ops[0]["inverse"]["op_type"] == "replace_spec"
    # undo restores the def (exact snapshot) and removes the real field
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    contact = next(e for e in spec["entities"] if e["name"] == "Contact")
    assert not any(f["name"] == "region" for f in contact["fields"])
    assert "region" in [d["name"] for d in contact["custom_fields"]["defs"]]
    # remove
    assert (await client.delete(url(pid, "region"))).status_code == 204
    assert (await client.delete(url(pid, "region"))).status_code == 404


async def test_define_enables_custom_fields_on_a_plain_entity(client: AsyncClient) -> None:
    pid = await project(client)
    listed = (await client.get(url(pid, entity="Note"))).json()
    assert listed["enabled"] is False and listed["items"] == []
    r = await client.post(url(pid, entity="Note"), json={"name": "flag", "type": "bool"})
    assert r.status_code == 201, r.text
    assert (await client.get(url(pid, entity="Note"))).json()["enabled"] is True


async def test_entity_patch_keeps_custom_fields(client: AsyncClient) -> None:
    pid = await project(client)
    ents = (await client.get(f"/projects/{pid}/entities")).json()["items"]
    contact = next(e for e in ents if e["name"] == "Contact")
    r = await client.patch(f"/entities/{contact['id']}", json={"options": {"default_page_size": 25}})
    assert r.status_code == 200, r.text
    assert "score" in [d["name"] for d in (await client.get(url(pid))).json()["items"]]


async def test_roles_and_unknown_entity(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await project(client)
    vi = await client_for("vi@example.com")
    await add_to_project_org(pid, "vi@example.com")
    r = await client.post(f"/projects/{pid}/members", json={"email": "vi@example.com", "role": "viewer"})
    assert r.status_code == 201, r.text
    assert (await vi.get(url(pid))).status_code == 200
    write: list[Any] = [
        await vi.post(url(pid), json={"name": "z", "type": "int"}),
        await vi.patch(url(pid, "score"), json={"required": True}),
        await vi.delete(url(pid, "score")),
        await vi.post(url(pid, "score", "promote-check")),
        await vi.post(url(pid, "score", "promote")),
    ]
    assert [w.status_code for w in write] == [403] * 5
    assert (await client.get(url(pid, entity="Nope"))).status_code == 404
    assert (await client.post(url(pid, entity="Nope"), json={"name": "z", "type": "int"})).status_code == 404
    assert (await client.post(url(pid, "score", "promote-check", entity="Nope"))).status_code == 404
    assert (await client.post(url(pid, "missing", "promote-check"))).status_code == 404
    assert (await client.post(url(pid, "missing", "promote"))).status_code == 404
