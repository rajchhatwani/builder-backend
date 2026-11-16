"""The row-by-row access routes accept the same edit once `confirm_weakening` is given."""

from httpx import AsyncClient

from tests.api.conftest import ClientFor
from tests.api.test_access_layers import project_with_spec


async def _perm_ids(c: AsyncClient, pid: str) -> dict[str, str]:
    body = (await c.get(f"/projects/{pid}/permissions")).json()
    return {p["operation"]: p["id"] for p in body["items"]}


async def test_confirmed_role_and_permission_and_auth_edits_apply(client_for: ClientFor) -> None:
    a = await client_for("owner@example.com")
    pid, _ = await project_with_spec(a)
    roles = {r["name"]: r for r in (await a.get(f"/projects/{pid}/roles")).json()["items"]}
    r = await a.patch(
        f"/roles/{roles['staff']['id']}", json={"inherits_from": "admin", "confirm_weakening": True}
    )
    assert r.status_code == 200 and r.json()["inherits_from"] == "admin", r.text
    ids = await _perm_ids(a, pid)
    r = await a.delete(f"/permissions/{ids['delete']}?confirm_weakening=true")
    assert r.status_code == 204
    assert "delete" not in await _perm_ids(a, pid)
    r = await a.patch(f"/projects/{pid}/auth", json={"enabled": False, "confirm_weakening": True})
    assert r.status_code == 200 and r.json()["enabled"] is False, r.text
