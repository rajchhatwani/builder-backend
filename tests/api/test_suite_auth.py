"""The builder API carries `suite` (auth.suite) unchanged: PATCH /projects/{id}/auth and the spec."""

from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_auth, make_project

SUITE: dict[str, Any] = {
    "suite_id": "acme",
    "hub_issuer": "https://id.acme.com/realms/suite-acme",
    "join_state": "planned",
}


async def test_suite_is_empty_by_default(client: AsyncClient) -> None:
    project_id = await make_project(client)
    created = await make_auth(client, project_id)
    assert created["suite"] is None


async def test_patch_sets_and_returns_the_suite_unchanged(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    patched = await client.patch(f"/projects/{project_id}/auth", json={"suite": SUITE})
    assert patched.status_code == 200, patched.text
    assert patched.json()["suite"] == SUITE

    got = await client.get(f"/projects/{project_id}/auth")
    assert got.json()["suite"] == SUITE


async def test_other_patches_leave_the_suite_alone_and_null_removes_it(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)
    await client.patch(f"/projects/{project_id}/auth", json={"suite": SUITE})

    other = await client.patch(f"/projects/{project_id}/auth", json={"app_name": "Portal"})
    assert other.json()["suite"] == SUITE

    cleared = await client.patch(f"/projects/{project_id}/auth", json={"suite": None})
    assert cleared.json()["suite"] is None


async def test_a_malformed_suite_is_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)
    bad = await client.patch(
        f"/projects/{project_id}/auth", json={"suite": {"suite_id": "Not Valid"}}
    )
    assert bad.status_code == 422


async def test_the_suite_round_trips_through_the_spec(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)
    await client.patch(f"/projects/{project_id}/auth", json={"suite": SUITE})

    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    assert spec["auth"]["suite"] == SUITE

    # The spec check refuses a suite on built-in auth, so the PUT switches to a shared realm.
    spec["auth"]["provider"] = "keycloak"
    spec["auth"]["keycloak"] = {
        "mode": "shared",
        "realm": "suite-acme",
        "api_client_id": "portal-api",
        "web_client_id": "portal-web",
        "redirect_uris": ["http://localhost:3000/"],
    }
    spec["auth"]["smtp"] = None
    spec["auth"]["password_reset"]["email_magic_link"] = False
    spec["auth"]["registration"]["email_verification_required"] = False
    spec["auth"]["suite"]["join_state"] = "joined"
    put = await client.put(f"/projects/{project_id}/spec", json=spec)
    assert put.status_code == 200, put.text
    again = (await client.get(f"/projects/{project_id}/spec")).json()
    assert again["auth"]["suite"] == {**SUITE, "join_state": "joined"}

    spec["auth"]["suite"] = None
    await client.put(f"/projects/{project_id}/spec", json=spec)
    final = (await client.get(f"/projects/{project_id}/spec")).json()
    assert final["auth"]["suite"] is None
