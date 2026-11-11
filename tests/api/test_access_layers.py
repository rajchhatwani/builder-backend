"""B4-7 access layers over the API: field_access persistence, matrix, access-diff, and the refusal
of an op-log edit that gives a role more access."""

import copy
from typing import Any

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.unit.test_access_layers import base


async def project_with_spec(client: AsyncClient) -> tuple[str, dict[str, Any]]:
    project_id = await make_project(client, "People")
    raw = base()
    raw["project"] = {"name": "People", "slug": "people", "description": None, "db_engine": "postgres"}
    response = await client.put(f"/projects/{project_id}/spec", json=raw)
    assert response.status_code == 200, response.text
    return project_id, raw


async def test_field_access_round_trips_and_matrix(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    project_id, _ = await project_with_spec(client)
    got = (await client.get(f"/projects/{project_id}/authorization")).json()
    assert got["field_access"][0]["field"] == "salary"
    assert got["field_access"][0]["read_roles"] == ["hr", "admin"]
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    assert spec["authorization"]["field_access"] == got["field_access"]
    m = (await client.get(f"/projects/{project_id}/access/matrix")).json()
    cells = {(c["layer"], c["target"], c["role"]): c["value"] for c in m["cells"]}
    assert cells[("field", "salary.read", "staff")] == "no"
    assert cells[("field", "salary.read", "hr")] == "yes"
    assert "(public)" in m["roles"]


async def test_diff_lists_exact_roles_and_writes_nothing(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    project_id, raw = await project_with_spec(client)
    perms = copy.deepcopy(raw["auth"]["permissions"])
    for p in perms:
        if p["operation"] == "delete":
            p["roles"] = ["admin", "staff"]
    response = await client.post(
        f"/projects/{project_id}/access/diff",
        json={"permissions": perms, "field_access": []},
    )
    assert response.status_code == 200, response.text
    d = response.json()
    assert d["weakens"] is True
    # staff: delete + salary.read; admin: salary.write (the field rule that narrowed it is gone)
    assert set(d["roles_gaining"]) == {"staff", "admin"}
    assert d["roles_gaining"]["admin"] == ["field:Person.salary.write"]
    assert any(c["layer"] == "object" and c["target"] == "delete" and c["role"] == "staff" for c in d["changes"])
    # emptying field_access lets staff read salary, hr gains nothing new on read
    assert "field:Person.salary.read" in d["roles_gaining"]["staff"]
    # nothing was saved
    again = (await client.get(f"/projects/{project_id}/spec")).json()
    assert again["authorization"]["field_access"] == raw["authorization"]["field_access"]


async def test_op_that_weakens_access_is_refused_until_confirmed(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    project_id, raw = await project_with_spec(client)
    weaker = copy.deepcopy(raw)
    weaker["authorization"]["field_access"] = []
    body = {"op_type": "replace_spec", "payload": {"spec": weaker}}
    refused = await client.post(f"/projects/{project_id}/spec/ops", json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "access_weakened"
    live = (await client.get(f"/projects/{project_id}/spec")).json()
    assert live["authorization"]["field_access"]  # unchanged
    ok = await client.post(f"/projects/{project_id}/spec/ops", json={**body, "confirm_weakening": True})
    assert ok.status_code == 201, ok.text
    live = (await client.get(f"/projects/{project_id}/spec")).json()
    assert live["authorization"]["field_access"] == []
    # tightening needs no confirmation
    stricter = copy.deepcopy(raw)
    ok2 = await client.post(
        f"/projects/{project_id}/spec/ops", json={"op_type": "replace_spec", "payload": {"spec": stricter}}
    )
    assert ok2.status_code == 201, ok2.text


async def test_viewer_cannot_use_diff_for_another_project(client_for: ClientFor) -> None:
    owner = await client_for("a@example.com")
    project_id, _ = await project_with_spec(owner)
    other = await client_for("b@example.com")
    assert (await other.get(f"/projects/{project_id}/access/matrix")).status_code in (403, 404)
    assert (await other.post(f"/projects/{project_id}/access/diff", json={})).status_code in (403, 404)


async def test_undo_restore_and_put_cannot_reopen_access_silently(client_for: ClientFor) -> None:
    client = await client_for("a@example.com")
    project_id, raw = await project_with_spec(client)
    tight = copy.deepcopy(raw)
    for p in tight["auth"]["permissions"]:
        if p["operation"] == "list":
            p["roles"] = ["admin"]  # staff and hr lose list
    first = await client.post(
        f"/projects/{project_id}/spec/ops", json={"op_type": "replace_spec", "payload": {"spec": tight}}
    )
    assert first.status_code == 201, first.text  # tightening needs no confirmation
    tighter = copy.deepcopy(tight)
    for p in tighter["auth"]["permissions"]:
        if p["operation"] == "create":
            p["roles"] = ["admin"]  # hr loses create
    second = await client.post(
        f"/projects/{project_id}/spec/ops", json={"op_type": "replace_spec", "payload": {"spec": tighter}}
    )
    assert second.status_code == 201, second.text
    # restoring to after op 1 re-opens create for hr: refused and rolled back
    restore = await client.post(f"/projects/{project_id}/spec/restore", json={"to_seq": 1})
    assert restore.status_code == 409 and restore.json()["code"] == "access_weakened"
    # undoing the second op re-opens create for hr: refused, then allowed when confirmed
    undo = await client.post(f"/projects/{project_id}/spec/undo")
    assert undo.status_code == 409 and undo.json()["code"] == "access_weakened"
    live = (await client.get(f"/projects/{project_id}/spec")).json()
    assert next(p["roles"] for p in live["auth"]["permissions"] if p["operation"] == "create") == ["admin"]
    ok = await client.post(f"/projects/{project_id}/spec/undo?confirm_weakening=true")
    assert ok.status_code == 200, ok.text
    # PUT /authorization: dropping a field rule widens salary access
    block = (await client.get(f"/projects/{project_id}/authorization")).json()
    body = {"model": "rbac", "policies": [], "attachments": {}, "field_access": []}
    refused = await client.put(f"/projects/{project_id}/authorization", json=body)
    assert refused.status_code == 409 and refused.json()["code"] == "access_weakened"
    assert (await client.get(f"/projects/{project_id}/authorization")).json()["field_access"] == block["field_access"]
    done = await client.put(f"/projects/{project_id}/authorization", json={**body, "confirm_weakening": True})
    assert done.status_code == 200, done.text


def _list_roles(spec: dict[str, Any]) -> list[str]:
    return next(p["roles"] for p in spec["auth"]["permissions"] if p["operation"] == "list")


async def test_apply_batch_refuses_a_net_access_gain_unless_confirmed(
    client_for: ClientFor, session_factory: Any
) -> None:
    """WP-A (c): the agent-draft batch path runs the same weakening check as single ops."""
    from sqlalchemy import func, select

    from app.exceptions import AppError
    from app.models.spec_op import SpecOp
    from app.services.ops.canon import canonical_hash
    from app.services.ops.scope import SYSTEM
    from app.services.ops.service import OpsService
    from app.services.spec_service import SpecService

    import uuid

    client = await client_for("a@example.com")
    project_id, raw = await project_with_spec(client)
    wide = copy.deepcopy(raw)
    for p in wide["auth"]["permissions"]:
        if p["operation"] == "delete":
            p["roles"] = ["admin", "staff"]  # staff gains delete

    async def run(confirm: bool) -> int:
        async with session_factory() as s:
            pid = uuid.UUID(project_id)
            live = await SpecService(s).assemble(pid)
            top = (await s.execute(select(func.coalesce(func.max(SpecOp.seq), 0)).where(SpecOp.project_id == pid))).scalar_one()
            from app.core.spec_models import Spec

            target = Spec.model_validate(wide)
            return await OpsService(s).apply_batch(
                pid, [("replace_spec", {"spec": wide})], SYSTEM, base_seq=int(top),
                expect_before=canonical_hash(live), expect_after=canonical_hash(target),
                confirm_weakening=confirm,
            )  # fmt: skip

    with pytest.raises(AppError) as exc:
        await run(False)
    assert exc.value.code == "access_weakened" and exc.value.status_code == 409
    live = (await client.get(f"/projects/{project_id}/spec")).json()
    assert next(p["roles"] for p in live["auth"]["permissions"] if p["operation"] == "delete") == ["admin"]
    assert await run(True) == 1
    live = (await client.get(f"/projects/{project_id}/spec")).json()
    assert "staff" in next(p["roles"] for p in live["auth"]["permissions"] if p["operation"] == "delete")
