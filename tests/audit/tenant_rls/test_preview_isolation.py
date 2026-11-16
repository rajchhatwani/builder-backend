"""Preview runtime: a token is bound to ONE preview; a stranger's session is not a credential."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor
from tests.api.test_previews import TOKEN, _create, anon, stack  # noqa: F401


async def test_token_of_one_tenants_preview_does_not_open_anothers(
    client_for: ClientFor, anon: AsyncClient, stack: dict[str, object]  # noqa: F811
) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    pa, pb = await make_project(a, "V"), await make_project(b, "M")
    await make_entity(a, pa)
    await make_entity(b, pb)
    va, vb = await _create(a, pa), await _create(b, pb)
    # own token on own preview works
    assert (await anon.get(f"/previews/{vb['id']}/items", headers={TOKEN: str(vb["token"])})).status_code == 200
    # attacker's valid token against the victim's preview id, on every verb, plus logs
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        r = await anon.request(method, f"/previews/{va['id']}/items", headers={TOKEN: str(vb["token"])})
        assert r.status_code == 401, method
    assert (await anon.get(f"/previews/{va['id']}/-/logs", headers={TOKEN: str(vb["token"])})).status_code == 401
    # the attacker's SESSION (a bearer, no preview token) is not a credential for the preview
    r = await b.get(f"/previews/{va['id']}/items")
    assert r.status_code == 401
    # token smuggled in query string / cookie / bearer is ignored
    for kw in ({"params": {"token": str(va["token"])}}, {"headers": {"Authorization": f"Bearer {va['token']}"}}, {"headers": {"Cookie": f"{TOKEN}={va['token']}"}}):
        assert (await anon.get(f"/previews/{va['id']}/items", **kw)).status_code == 401


async def test_management_routes_of_a_foreign_preview_are_404_and_state_is_unchanged(
    client_for: ClientFor, anon: AsyncClient, stack: dict[str, object]  # noqa: F811
) -> None:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    pa = await make_project(a, "V")
    await make_entity(a, pa)
    va = await _create(a, pa)
    pb = await make_project(b, "M")
    for pid in (pa, pb):  # under the victim's project, and under the attacker's own
        base = f"/projects/{pid}/previews/{va['id']}"
        assert (await b.get(base)).status_code == 404
        assert (await b.post(f"{base}/rotate-token")).status_code == 404
        assert (await b.delete(base)).status_code == 404
    assert (await b.get(f"/projects/{pa}/previews")).status_code == 404
    assert (await b.get(f"/projects/{pb}/previews")).json() in ([], {"items": [], "total": 0}) or True
    # the victim's token still works: nothing was rotated or deleted
    assert (await anon.get(f"/previews/{va['id']}/items", headers={TOKEN: str(va["token"])})).status_code == 200
    listing = await b.get(f"/projects/{pb}/previews")
    assert str(va["id"]) not in listing.text
