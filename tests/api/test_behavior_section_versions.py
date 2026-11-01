"""CO-5: every behaviour section has its own version; roles list for the pickers."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_auth, make_project, make_role
from tests.api.conftest import ClientFor, add_to_project_org

SETTING = {"key": "vat_rate", "type": "int", "default": 20}


def url(project_id: str, section: str) -> str:
    return f"/projects/{project_id}/behavior/{section}"


async def test_stale_write_to_section_a_succeeds_when_only_section_b_changed(
    client: AsyncClient,
) -> None:
    pid = await make_project(client)
    first = await client.put(url(pid, "state-machines"), json={"state_machines": []})
    assert first.json()["version"] == 1
    # Another page saves a different section in between.
    other = await client.put(url(pid, "settings"), json={"settings": [SETTING]})
    assert other.status_code == 200 and other.json()["version"] == 1
    again = await client.put(
        url(pid, "state-machines"), json={"state_machines": [], "expected_version": 1}
    )
    assert again.status_code == 200, again.text
    assert again.json()["version"] == 2
    # The settings section kept its own data and version.
    got = (await client.get(url(pid, "settings"))).json()
    assert got["version"] == 1 and got["settings"][0]["key"] == "vat_rate"
    assert got["row_version"] == 3  # informational whole-row counter, one bump per save


async def test_stale_write_to_the_same_section_is_a_409(client: AsyncClient) -> None:
    pid = await make_project(client)
    await client.put(url(pid, "settings"), json={"settings": []})
    assert (
        await client.put(url(pid, "settings"), json={"settings": [], "expected_version": 1})
    ).status_code == 200
    stale = await client.put(url(pid, "settings"), json={"settings": [], "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"


async def test_never_saved_section_is_version_zero_even_if_siblings_exist(
    client: AsyncClient,
) -> None:
    pid = await make_project(client)
    await client.put(url(pid, "hooks"), json={"hooks": []})
    assert (await client.get(url(pid, "seed"))).json()["version"] == 0
    ok = await client.put(url(pid, "seed"), json={"seed": [], "expected_version": 0})
    assert ok.status_code == 200 and ok.json()["version"] == 1


async def test_roles_list_returns_declared_roles_only(client: AsyncClient) -> None:
    pid = await make_project(client)
    empty = await client.get(url(pid, "roles"))
    assert empty.status_code == 200 and empty.json()["roles"] == []
    await make_auth(client, pid)
    await make_role(client, pid, "manager")
    body = (await client.get(url(pid, "roles"))).json()
    assert [r["name"] for r in body["roles"]].count("manager") == 1
    assert set(body["roles"][0]) == {"name", "label"}
    assert "smtp" not in str(body).lower()


async def test_roles_list_is_tenant_isolated_and_viewer_readable(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    stranger = await client_for("stranger@example.com")
    viewer = await client_for("viewer@example.com")
    pid = await make_project(owner)
    await make_auth(owner, pid)
    await make_role(owner, pid, "manager")
    await add_to_project_org(pid, "viewer@example.com")
    added = await owner.post(
        f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    assert (await viewer.get(url(pid, "roles"))).status_code == 200
    assert (await stranger.get(url(pid, "roles"))).status_code == 404
    other = await make_project(stranger)
    mine = (await stranger.get(url(other, "roles"))).json()
    assert "manager" not in [r["name"] for r in mine["roles"]]
