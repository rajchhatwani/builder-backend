import uuid

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project, make_role


async def test_create_and_get_role(client: AsyncClient) -> None:
    project_id = await make_project(client)

    created = await make_role(client, project_id, "admin", self_assignable=False, position=2)

    assert created["name"] == "admin"
    assert created["label"] == "Admin"
    assert created["is_default"] is False
    assert created["inherits_from"] is None
    fetched = await client.get(f"/roles/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


@pytest.mark.parametrize("name", ["Admin", "1admin", "ad-min", "ad min", 'a"; drop', ""])
async def test_role_names_must_be_lowercase_identifiers(client: AsyncClient, name: str) -> None:
    project_id = await make_project(client)

    response = await client.post(
        f"/projects/{project_id}/roles", json={"name": name, "label": "Label"}
    )

    assert response.status_code == 422


async def test_duplicate_role_name_conflicts(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_role(client, project_id, "admin")

    response = await client.post(
        f"/projects/{project_id}/roles", json={"name": "admin", "label": "Again"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_same_role_name_in_different_projects_is_fine(client: AsyncClient) -> None:
    first = await make_project(client, "One")
    second = await make_project(client, "Two")

    await make_role(client, first, "admin")
    await make_role(client, second, "admin")


async def test_only_one_default_role(client: AsyncClient) -> None:
    project_id = await make_project(client)
    member = await make_role(client, project_id, "member", is_default=True)

    second = await client.post(
        f"/projects/{project_id}/roles",
        json={"name": "guest", "label": "Guest", "is_default": True},
    )
    assert second.status_code == 409

    guest = await make_role(client, project_id, "guest")
    promote = await client.patch(f"/roles/{guest['id']}", json={"is_default": True})
    assert promote.status_code == 409

    # Swap: demote the current default first, then the other can take over.
    assert (
        await client.patch(f"/roles/{member['id']}", json={"is_default": False})
    ).status_code == 200
    assert (
        await client.patch(f"/roles/{guest['id']}", json={"is_default": True})
    ).status_code == 200


async def test_default_role_cannot_be_deleted(client: AsyncClient) -> None:
    project_id = await make_project(client)
    member = await make_role(client, project_id, "member", is_default=True)

    response = await client.delete(f"/roles/{member['id']}")

    assert response.status_code == 409


async def test_inherits_from_must_exist(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.post(
        f"/projects/{project_id}/roles",
        json={"name": "editor", "label": "Editor", "inherits_from": "ghost"},
    )

    assert response.status_code == 422


async def test_inherits_from_is_scoped_to_the_project(client: AsyncClient) -> None:
    first = await make_project(client, "One")
    second = await make_project(client, "Two")
    await make_role(client, first, "admin")

    response = await client.post(
        f"/projects/{second}/roles",
        json={"name": "editor", "label": "Editor", "inherits_from": "admin"},
    )

    assert response.status_code == 422


async def test_role_cannot_inherit_from_itself(client: AsyncClient) -> None:
    project_id = await make_project(client)
    role = await make_role(client, project_id, "editor")

    response = await client.patch(f"/roles/{role['id']}", json={"inherits_from": "editor"})

    assert response.status_code == 422


async def test_indirect_inheritance_cycles_are_rejected(client: AsyncClient) -> None:
    project_id = await make_project(client)
    admin = await make_role(client, project_id, "admin")
    editor = await make_role(client, project_id, "editor", inherits_from="admin")
    viewer = await make_role(client, project_id, "viewer", inherits_from="editor")

    direct = await client.patch(f"/roles/{admin['id']}", json={"inherits_from": "editor"})
    indirect = await client.patch(f"/roles/{admin['id']}", json={"inherits_from": "viewer"})

    assert direct.status_code == indirect.status_code == 422
    assert "cycle" in indirect.text
    # Nothing was changed by the rejected requests.
    assert (await client.get(f"/roles/{admin['id']}")).json()["inherits_from"] is None
    assert editor["inherits_from"] == "admin" and viewer["inherits_from"] == "editor"


async def test_role_with_dependants_cannot_be_deleted(client: AsyncClient) -> None:
    project_id = await make_project(client)
    admin = await make_role(client, project_id, "admin")
    editor = await make_role(client, project_id, "editor", inherits_from="admin")

    blocked = await client.delete(f"/roles/{admin['id']}")
    assert blocked.status_code == 409

    assert (await client.delete(f"/roles/{editor['id']}")).status_code == 204
    assert (await client.delete(f"/roles/{admin['id']}")).status_code == 204
    assert (await client.get(f"/roles/{admin['id']}")).status_code == 404


async def test_update_role_fields(client: AsyncClient) -> None:
    project_id = await make_project(client)
    role = await make_role(client, project_id, "editor")

    response = await client.patch(
        f"/roles/{role['id']}",
        json={"label": "Chief Editor", "self_assignable": True, "position": 5},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "Chief Editor"
    assert body["self_assignable"] is True
    assert body["position"] == 5
    assert body["name"] == "editor"


async def test_list_is_ordered_by_position_and_paginated(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_role(client, project_id, "c_last", position=3)
    await make_role(client, project_id, "a_first", position=1)
    await make_role(client, project_id, "b_middle", position=2)

    listing = (await client.get(f"/projects/{project_id}/roles")).json()
    assert [r["name"] for r in listing["items"]] == ["a_first", "b_middle", "c_last"]
    assert listing["total"] == 3

    page = (
        await client.get(f"/projects/{project_id}/roles", params={"limit": 1, "offset": 1})
    ).json()
    assert [r["name"] for r in page["items"]] == ["b_middle"]
    assert page["total"] == 3


async def test_roles_are_per_project(client: AsyncClient) -> None:
    first = await make_project(client, "One")
    second = await make_project(client, "Two")
    await make_role(client, first, "admin")

    assert (await client.get(f"/projects/{second}/roles")).json()["total"] == 0


async def test_missing_things_are_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    project_id = await make_project(client)
    assert (
        await client.post(f"/projects/{missing}/roles", json={"name": "a", "label": "A"})
    ).status_code == 404
    assert (await client.get(f"/projects/{missing}/roles")).status_code == 404
    assert (await client.get(f"/roles/{missing}")).status_code == 404
    assert (await client.patch(f"/roles/{missing}", json={"label": "x"})).status_code == 404
    assert (await client.delete(f"/roles/{missing}")).status_code == 404
    assert (await client.get(f"/projects/{project_id}/roles")).status_code == 200


async def test_roles_are_removed_with_their_project(client: AsyncClient) -> None:
    project_id = await make_project(client)
    role = await make_role(client, project_id, "admin")

    await client.delete(f"/projects/{project_id}")

    assert (await client.get(f"/roles/{role['id']}")).status_code == 404
