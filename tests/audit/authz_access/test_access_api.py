"""Access-layer edits over the builder API: every route that can give a role more access must
refuse without `confirm_weakening`, viewers must not reach any of them, and nothing may be applied
by a request that was refused."""

import asyncio
import copy
from typing import Any

from httpx import AsyncClient

from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_access_layers import project_with_spec


async def _member(owner: AsyncClient, project_id: str, who: AsyncClient, role: str) -> None:
    await add_to_project_org(project_id, who.user.email)  # type: ignore[attr-defined]
    r = await owner.post(
        f"/projects/{project_id}/members", json={"email": who.user.email, "role": role}  # type: ignore[attr-defined]
    )
    assert r.status_code == 201, r.text


async def _roles(c: AsyncClient, pid: str) -> dict[str, dict[str, Any]]:
    body = (await c.get(f"/projects/{pid}/roles")).json()
    return {r["name"]: r for r in (body["items"] if isinstance(body, dict) else body)}


async def _perm_ids(c: AsyncClient, pid: str) -> dict[str, str]:
    return {p["operation"]: p["id"] for p in await _perm_rows(c, pid)}


async def _perm_rows(c: AsyncClient, pid: str) -> list[dict[str, Any]]:
    body = (await c.get(f"/projects/{pid}/permissions")).json()
    return list(body["items"] if isinstance(body, dict) else body)


async def test_role_inherits_from_patch_needs_confirmation(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    roles = await _roles(a, pid)
    r = await a.patch(f"/roles/{roles['staff']['id']}", json={"inherits_from": "admin"})
    assert r.status_code == 409, f"staff now inherits admin with no confirmation: {r.status_code} {r.text[:120]}"
    assert (await _roles(a, pid))["staff"]["inherits_from"] is None


async def test_making_admin_role_self_assignable_needs_confirmation(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    roles = await _roles(a, pid)
    r = await a.patch(f"/roles/{roles['admin']['id']}", json={"self_assignable": True})
    assert r.status_code in (409, 422), f"anyone can now sign up as admin: {r.status_code}"
    assert (await _roles(a, pid))["admin"]["self_assignable"] is False


async def test_making_admin_role_default_needs_confirmation(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    roles = await _roles(a, pid)
    r = await a.patch(f"/roles/{roles['admin']['id']}", json={"is_default": True})
    assert r.status_code in (409, 422), f"every new sign-up is now admin: {r.status_code}"
    assert (await _roles(a, pid))["admin"]["is_default"] is False


async def test_replace_spec_adding_powerful_self_assignable_role_needs_confirmation(
    client_for: ClientFor,
) -> None:
    a = await client_for("owner@example.com")
    pid, raw = await project_with_spec(a)
    evil = copy.deepcopy(raw)
    evil["auth"]["roles"].append({"name": "root", "label": "Root", "self_assignable": True})
    for p in evil["auth"]["permissions"]:
        p["roles"].append("root")
    r = await a.post(f"/projects/{pid}/spec/ops", json={"op_type": "replace_spec", "payload": {"spec": evil}})
    assert r.status_code == 409, f"{r.status_code}: a self-assignable root role went in unconfirmed"


async def test_put_spec_weakening_needs_confirmation(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, raw = await project_with_spec(a)
    weaker = copy.deepcopy(raw)
    weaker["authorization"]["field_access"] = []
    r = await a.put(f"/projects/{pid}/spec", json=weaker)
    assert r.status_code == 409, r.text[:200]
    live = (await a.get(f"/projects/{pid}/spec")).json()
    assert live["authorization"]["field_access"] == raw["authorization"]["field_access"]


async def test_deleting_a_permission_slot_makes_the_route_public_and_needs_confirmation(
    client_for: ClientFor,
) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    ids = await _perm_ids(a, pid)
    r = await a.delete(f"/permissions/{ids['delete']}")
    assert r.status_code == 409, f"delete slot removed without confirmation: {r.status_code}"
    assert "delete" in await _perm_ids(a, pid)


async def test_emptying_permission_roles_needs_confirmation(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    ids = await _perm_ids(a, pid)
    r = await a.patch(f"/permissions/{ids['delete']}", json={"roles": []})
    assert r.status_code == 409, r.text[:200]
    after = {p["operation"]: p["roles"] for p in await _perm_rows(a, pid)}
    assert after["delete"] == ["admin"]


async def test_disabling_sign_in_needs_confirmation(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    r = await a.patch(f"/projects/{pid}/auth", json={"enabled": False})
    assert r.status_code in (409, 422), f"sign-in switched off with all rules attached: {r.status_code}"
    cfg = (await a.get(f"/projects/{pid}/auth")).json()
    assert cfg["enabled"] is True


async def test_parallel_unconfirmed_weakening_is_refused_every_time(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    ids = await _perm_ids(a, pid)

    async def go(i: int) -> int:
        roles = ["admin", "staff"] if i % 2 else ["admin", "hr", "staff"]
        return (await a.patch(f"/permissions/{ids['delete']}", json={"roles": roles})).status_code

    codes = await asyncio.gather(*(go(i) for i in range(8)))
    assert set(codes) == {409}, codes
    after = {p["operation"]: p["roles"] for p in await _perm_rows(a, pid)}
    assert after["delete"] == ["admin"]


async def test_viewer_cannot_reach_any_access_edit_route(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    v = await client_for("viewer@example.com")
    pid, raw = await project_with_spec(a)
    await _member(a, pid, v, "viewer")
    roles = await _roles(a, pid)
    ids = await _perm_ids(a, pid)
    calls = [
        ("PUT", f"/projects/{pid}/spec", raw),
        ("PUT", f"/projects/{pid}/authorization", {"field_access": [], "confirm_weakening": True}),
        ("POST", f"/projects/{pid}/spec/ops", {"op_type": "replace_spec", "payload": {"spec": raw}, "confirm_weakening": True}),
        ("PATCH", f"/roles/{roles['staff']['id']}", {"inherits_from": "admin"}),
        ("DELETE", f"/roles/{roles['staff']['id']}", None),
        ("PATCH", f"/permissions/{ids['delete']}", {"roles": [], "confirm_weakening": True}),
        ("DELETE", f"/permissions/{ids['delete']}", None),
        ("POST", f"/projects/{pid}/spec/undo", None),
        ("POST", f"/projects/{pid}/spec/restore", {"to_seq": 1, "confirm_weakening": True}),
        ("PATCH", f"/projects/{pid}/auth", {"enabled": False}),
        ("PUT", f"/projects/{pid}/auth/secrets", {}),
    ]
    bad = []
    for m, p, body in calls:
        r = await v.request(m, p, json=body) if body is not None else await v.request(m, p)
        if r.status_code not in (403, 404):
            bad.append(f"{m} {p} -> {r.status_code}")
    assert bad == []
    assert (await _roles(a, pid))["staff"]["inherits_from"] is None


async def test_non_member_gets_404_on_every_access_route(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    x = await client_for("stranger@example.com")
    pid, _ = await project_with_spec(a)
    roles = await _roles(a, pid)
    ids = await _perm_ids(a, pid)
    for m, p in (
        ("GET", f"/projects/{pid}/access/matrix"),
        ("GET", f"/projects/{pid}/authorization"),
        ("GET", f"/roles/{roles['admin']['id']}"),
        ("GET", f"/permissions/{ids['delete']}"),
        ("POST", f"/projects/{pid}/access/diff"),
        ("GET", f"/projects/{pid}/spec/ops"),
    ):
        r = await x.request(m, p, json={} if m == "POST" else None)
        assert r.status_code == 404, f"{m} {p} -> {r.status_code}"


async def test_editor_cannot_promote_self_or_add_an_owner(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    e = await client_for("editor@example.com")
    o = await client_for("other@example.com")
    pid = (await project_with_spec(a))[0]
    await _member(a, pid, e, "editor")
    await add_to_project_org(pid, o.user.email)  # type: ignore[attr-defined]
    me = str(e.user.id)  # type: ignore[attr-defined]
    assert (await e.patch(f"/projects/{pid}/members/{me}", json={"role": "owner"})).status_code == 403
    r = await e.post(f"/projects/{pid}/members", json={"email": o.user.email, "role": "owner"})  # type: ignore[attr-defined]
    assert r.status_code == 403
    assert (await e.delete(f"/projects/{pid}/members/{a.user.id}")).status_code == 403  # type: ignore[attr-defined]
    me_row = [m for m in (await a.get(f"/projects/{pid}/members")).json() if m["user_id"] == me][0]
    assert me_row["role"] == "editor"


async def test_two_owners_demoting_each_other_in_parallel_leave_one_owner(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    b = await client_for("coowner@example.com")
    pid = (await project_with_spec(a))[0]
    await _member(a, pid, b, "owner")
    ua, ub = str(a.user.id), str(b.user.id)  # type: ignore[attr-defined]
    res = await asyncio.gather(
        a.patch(f"/projects/{pid}/members/{ub}", json={"role": "viewer"}),
        b.patch(f"/projects/{pid}/members/{ua}", json={"role": "viewer"}),
        return_exceptions=True,
    )
    codes = [r.status_code for r in res if not isinstance(r, Exception)]
    assert not any(c >= 500 for c in codes), codes
    owners = [m for m in (await a.get(f"/projects/{pid}/members")).json() if m["role"] == "owner"]
    assert len(owners) >= 1, "the project was left without an owner"


async def test_last_owner_cannot_demote_or_leave(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid = (await project_with_spec(a))[0]
    me = str(a.user.id)  # type: ignore[attr-defined]
    r1 = await a.patch(f"/projects/{pid}/members/{me}", json={"role": "editor"})
    r2 = await a.delete(f"/projects/{pid}/members/{me}")
    assert r1.status_code == 409 and r2.status_code == 409, (r1.status_code, r2.status_code)


async def test_matrix_and_diff_are_read_only_even_with_a_bomb_body(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, raw = await project_with_spec(a)
    huge = {"permissions": raw["auth"]["permissions"] * 400, "field_access": []}
    r = await a.post(f"/projects/{pid}/access/diff", json=huge)
    assert r.status_code in (200, 413, 422), r.status_code
    again = (await a.get(f"/projects/{pid}/spec")).json()
    assert again["authorization"]["field_access"] == raw["authorization"]["field_access"]
