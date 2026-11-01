"""Spec op-log (B2-8): every change recorded with its actor, undo/redo/restore return the spec to
byte-identical canonical JSON, invalid ops record nothing, tenants are isolated, MCP shares the API."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_authz as authz
from app.core.spec_models import Spec
from app.models.spec_op import SpecOp
from app.services.mcp_service import McpService
from app.services.ops.canon import canonical_bytes
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor
from tests.api.test_mcp import _enable_mcp, _principal

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "specs"


async def _bytes(client: AsyncClient, pid: str) -> bytes:
    r = await client.get(f"/projects/{pid}/spec")
    assert r.status_code == 200, r.text
    return canonical_bytes(Spec.model_validate(r.json()))


async def _ops(client: AsyncClient, pid: str) -> list[dict[str, Any]]:
    r = await client.get(f"/projects/{pid}/spec/ops?limit=200")
    assert r.status_code == 200, r.text
    return list(reversed(r.json()["items"]))  # oldest first


async def _apply(client: AsyncClient, pid: str, op_type: str, payload: dict[str, Any]) -> Any:
    return await client.post(
        f"/projects/{pid}/spec/ops", json={"op_type": op_type, "payload": payload}
    )


async def test_rest_edits_are_recorded_with_actor_and_a_hash_chain(client: AsyncClient) -> None:
    pid = await make_project(client)
    eid = await make_entity(client, pid, "Item")
    await client.post(f"/entities/{eid}/fields", json={"name": "title", "type": "string"})
    other = await make_entity(client, pid, "Tag")
    await client.post(
        f"/projects/{pid}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": eid,
            "to_entity_id": other,
            "from_name": "tags",
            "to_name": "item",
        },
    )
    ops = await _ops(client, pid)
    assert [o["op_type"] for o in ops] == [
        "add_entity",
        "add_field",
        "add_entity",
        "add_relation",
    ]
    assert [o["seq"] for o in ops] == [1, 2, 3, 4]
    me = str(client.user.id)  # type: ignore[attr-defined]
    assert all(o["actor"]["kind"] == "user" and o["actor"]["user_id"] == me for o in ops)
    assert ops[0]["actor"]["email"] == "primary@example.com"
    for prev, cur in zip(ops, ops[1:], strict=False):
        assert prev["spec_hash_after"] == cur["spec_hash_before"]
    assert ops[0]["inverse"]["op_type"] == "remove_entity"


async def test_a_failed_rest_write_records_nothing(client: AsyncClient) -> None:
    pid = await make_project(client)
    await make_entity(client, pid, "Item")
    dup = await client.post(f"/projects/{pid}/entities", json={"name": "Item"})
    assert dup.status_code == 409
    assert len(await _ops(client, pid)) == 1


async def test_undo_redo_restores_byte_identical_spec(client: AsyncClient) -> None:
    pid = await make_project(client)
    states = [await _bytes(client, pid)]
    eid = await make_entity(client, pid, "Item")
    states.append(await _bytes(client, pid))
    for name in ("a", "b", "c"):
        await client.post(f"/entities/{eid}/fields", json={"name": name, "type": "string"})
        states.append(await _bytes(client, pid))
    other = await make_entity(client, pid, "Tag")
    states.append(await _bytes(client, pid))
    rel = {
        "kind": "one_to_many",
        "from_entity_id": eid,
        "to_entity_id": other,
        "from_name": "tags",
        "to_name": "item",
    }
    await client.post(f"/projects/{pid}/relations", json=rel)
    states.append(await _bytes(client, pid))

    for expected in reversed(states[:-1]):
        r = await client.post(f"/projects/{pid}/spec/undo")
        assert r.status_code == 200, r.text
        assert r.json()["origin"] == "undo"
        assert await _bytes(client, pid) == expected
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 409
    for expected in states[1:]:
        assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
        assert await _bytes(client, pid) == expected
    assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 409


async def test_a_new_change_clears_the_redo_stack(client: AsyncClient) -> None:
    pid = await make_project(client)
    await make_entity(client, pid, "Item")
    await client.post(f"/projects/{pid}/spec/undo")
    await make_entity(client, pid, "Tag")
    assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 409


async def test_deleting_an_entity_with_relations_undoes_exactly(client: AsyncClient) -> None:
    pid = await make_project(client)
    a, b = await make_entity(client, pid, "Author"), await make_entity(client, pid, "Book")
    await client.post(f"/entities/{a}/fields", json={"name": "name", "type": "string"})
    await client.post(
        f"/projects/{pid}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": a,
            "to_entity_id": b,
            "from_name": "books",
            "to_name": "author",
        },
    )
    before = await _bytes(client, pid)
    assert (await client.delete(f"/entities/{a}")).status_code == 204
    gone = await _bytes(client, pid)
    assert gone != before
    assert (await _ops(client, pid))[-1]["inverse"]["op_type"] == "replace_spec"
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) == before
    assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
    assert await _bytes(client, pid) == gone


async def test_typed_ops_apply_record_and_undo(client: AsyncClient) -> None:
    pid = await make_project(client)
    empty = await _bytes(client, pid)
    r = await _apply(
        client,
        pid,
        "add_entity",
        {
            "entity": {
                "name": "Invoice",
                "fields": [{"name": "total", "type": "decimal"}, {"name": "memo", "type": "text"}],
            }
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["op_type"] == "add_entity" and r.json()["seq"] == 1
    after_add = await _bytes(client, pid)
    r = await _apply(
        client,
        pid,
        "update_field",
        {"entity": "Invoice", "name": "total", "changes": {"required": True}},
    )
    assert r.status_code == 201, r.text
    r = await _apply(
        client,
        pid,
        "add_field",
        {"entity": "Invoice", "field": {"name": "paid", "type": "boolean"}, "index": 0},
    )
    assert r.status_code == 201, r.text
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    assert [f["name"] for f in spec["entities"][0]["fields"]] == ["paid", "total", "memo"]
    r = await _apply(
        client,
        pid,
        "set_section",
        {"section": "settings", "items": [{"key": "tax", "type": "int", "default": 1}]},
    )
    assert r.status_code == 201, r.text
    for _ in range(4):
        assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) == empty
    for _ in range(1):
        assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
    assert await _bytes(client, pid) == after_add


async def test_invalid_op_records_nothing_and_changes_nothing(client: AsyncClient) -> None:
    pid = await make_project(client)
    assert (
        await _apply(client, pid, "add_entity", {"entity": {"name": "Item"}})
    ).status_code == 201
    before, n = await _bytes(client, pid), len(await _ops(client, pid))
    # an enum field without values is a spec validation issue the op would introduce
    r = await _apply(
        client, pid, "add_field", {"entity": "Item", "field": {"name": "kind", "type": "enum"}}
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "spec_invalid"
    # a clash and a missing target are refused too
    assert (
        await _apply(client, pid, "add_entity", {"entity": {"name": "Item"}})
    ).status_code == 409
    assert (await _apply(client, pid, "remove_entity", {"name": "Nope"})).status_code == 404
    assert await _bytes(client, pid) == before
    assert len(await _ops(client, pid)) == n


async def test_unknown_op_type_and_bad_payload_are_422(client: AsyncClient) -> None:
    pid = await make_project(client)
    r = await _apply(client, pid, "drop_database", {})
    assert r.status_code == 422 and r.json()["code"] == "unknown_op_type"
    r = await _apply(client, pid, "add_entity", {"entity": {"name": "lower_case"}, "bogus": 1})
    assert r.status_code == 422 and r.json()["code"] == "invalid_op_payload"
    assert "lower_case" not in r.text
    assert await _ops(client, pid) == []


async def test_put_spec_and_restore_round_trip_a_full_fixture(client: AsyncClient) -> None:
    pid = await make_project(client, "Invoices")
    await make_entity(client, pid, "Seed")
    start = await _bytes(client, pid)
    body = json.loads((FIXTURES / "demo_invoice.json").read_text())
    body["project"] = (await client.get(f"/projects/{pid}/spec")).json()["project"]
    put = await client.put(f"/projects/{pid}/spec", json=body)
    assert put.status_code == 200, put.text
    full = await _bytes(client, pid)
    assert full != start
    ops = await _ops(client, pid)
    assert ops[-1]["op_type"] == "replace_spec"
    # undo clears blocks the fixture added (auth, behaviour sections) and returns the exact spec
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) == start
    assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
    assert await _bytes(client, pid) == full
    # restore to the state right after op 1, then to the empty beginning
    r = await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": 1})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == "restore"
    assert await _bytes(client, pid) == start
    r = await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": 0})
    assert r.status_code == 200, r.text
    assert (await client.get(f"/projects/{pid}/spec")).json()["entities"] == []
    # restore itself is undoable
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) == start
    last = (await _ops(client, pid))[-1]["seq"]
    assert (
        await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": last})
    ).status_code == 409
    assert (
        await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": last + 5})
    ).status_code == 404


async def test_restore_to_a_middle_state(client: AsyncClient) -> None:
    pid = await make_project(client)
    states = {0: await _bytes(client, pid)}
    for i, name in enumerate(("Alpha", "Beta", "Gamma", "Delta"), start=1):
        await make_entity(client, pid, name)
        states[i] = await _bytes(client, pid)
    r = await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": 2})
    assert r.status_code == 200, r.text
    assert await _bytes(client, pid) == states[2]
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) == states[4]


async def test_other_tenant_cannot_read_or_change_the_log(
    client: AsyncClient, client_for: ClientFor
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid, "Item")
    intruder = await client_for("intruder@example.com")
    for method, path, body in (
        ("get", f"/projects/{pid}/spec/ops", None),
        (
            "post",
            f"/projects/{pid}/spec/ops",
            {"op_type": "add_entity", "payload": {"entity": {"name": "X"}}},
        ),
        ("post", f"/projects/{pid}/spec/undo", None),
        ("post", f"/projects/{pid}/spec/redo", None),
        ("post", f"/projects/{pid}/spec/restore", {"to_seq": 0}),
    ):
        r = await getattr(intruder, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (path, r.status_code)
    assert len(await _ops(client, pid)) == 1


async def test_concurrent_applies_get_distinct_dense_seqs(client: AsyncClient) -> None:
    pid = await make_project(client)
    names = [f"Thing{c}" for c in "ABCDEFGH"]
    results = await asyncio.gather(
        *(_apply(client, pid, "add_entity", {"entity": {"name": n}}) for n in names)
    )
    assert [r.status_code for r in results] == [201] * len(names), [r.text for r in results]
    assert sorted(r.json()["seq"] for r in results) == list(range(1, len(names) + 1))
    ops = await _ops(client, pid)
    for prev, cur in zip(ops, ops[1:], strict=False):
        assert prev["spec_hash_after"] == cur["spec_hash_before"]  # a real chain, no lost update


async def test_mcp_edits_use_the_same_op_service_and_are_logged_as_mcp(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = client.user  # type: ignore[attr-defined]
    pid = await make_project(client)
    await _enable_mcp(session_factory, uuid.UUID(pid), user.id)
    principal = await _principal(user, scopes=(authz.SCOPE_MCP_WRITE,))
    async with session_factory() as db:
        ent = await McpService(db).create_entity(principal, uuid.UUID(pid), "Ticket")
        await McpService(db).add_field(
            principal, uuid.UUID(pid), "Ticket", {"name": "title", "type": "string"}
        )
        other = await McpService(db).create_entity(principal, uuid.UUID(pid), "Label")
        await McpService(db).add_relation(
            principal,
            uuid.UUID(pid),
            {
                "kind": "one_to_many",
                "from_entity_id": ent["id"],
                "to_entity_id": other["id"],
                "from_name": "labels",
                "to_name": "ticket",
            },
        )
    ops = await _ops(client, pid)
    assert [o["op_type"] for o in ops] == ["add_entity", "add_field", "add_entity", "add_relation"]
    assert {o["actor"]["kind"] for o in ops} == {"mcp"}
    assert {o["actor"]["user_id"] for o in ops} == {str(user.id)}
    # a dashboard user can undo what the MCP did, byte for byte
    spec_now = await _bytes(client, pid)
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) != spec_now
    assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
    assert await _bytes(client, pid) == spec_now


async def test_op_rows_hold_no_secret_material(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid, "Item")
    async with session_factory() as db:
        rows = (await db.execute(select(SpecOp))).scalars().all()
        total = (await db.execute(select(func.count()).select_from(SpecOp))).scalar_one()
    assert total == len(rows) == 1
    text = json.dumps([r.payload for r in rows] + [r.inverse for r in rows]).lower()
    for word in ("password", "secret", "token", "bearer"):
        assert word not in text


@pytest.mark.parametrize(
    "fixture",
    [
        "demo_invoice",
        "demo_leave",
        "blog",
        "shop_auth",
        "authz_pbac",
        "keycloak_own",
        "payments_stripe",
        "storage_s3",
        "obs_blog",
        "deploy_aws",
        "docs_desk",
        "seed_demo",
        "hooks_invoice",
    ],
)
async def test_undo_of_a_whole_spec_import_is_exact_for_every_block(
    client: AsyncClient, fixture: str
) -> None:
    pid = await make_project(client, "Imported")
    start = await _bytes(client, pid)
    body = json.loads((FIXTURES / f"{fixture}.json").read_text())
    body["project"] = (await client.get(f"/projects/{pid}/spec")).json()["project"]
    put = await client.put(f"/projects/{pid}/spec", json=body)
    assert put.status_code == 200, put.text
    full = await _bytes(client, pid)
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _bytes(client, pid) == start
    assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
    assert await _bytes(client, pid) == full
