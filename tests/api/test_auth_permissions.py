import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_entity, make_project, make_role


async def _setup(client: AsyncClient) -> tuple[str, str]:
    project_id = await make_project(client)
    entity_id = await make_entity(client, project_id)
    await make_role(client, project_id, "admin")
    await make_role(client, project_id, "member")
    return project_id, entity_id


def _entry(entity_id: str, operation: str = "list", **extra: Any) -> dict[str, Any]:
    return {"entity_id": entity_id, "operation": operation, "roles": ["admin"], **extra}


async def _upsert(client: AsyncClient, project_id: str, *entries: dict[str, Any]) -> Any:
    return await client.post(
        f"/projects/{project_id}/permissions", json={"permissions": list(entries)}
    )


async def test_bulk_upsert_returns_the_full_list(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)

    response = await _upsert(
        client,
        project_id,
        _entry(entity_id, "list", roles=[]),
        _entry(entity_id, "create", roles=["admin", "member"]),
        _entry(entity_id, "delete", row_rule="owner"),
    )

    assert response.status_code == 200, response.text
    by_op = {p["operation"]: p for p in response.json()}
    assert set(by_op) == {"list", "create", "delete"}
    assert by_op["list"]["roles"] == []  # empty = public
    assert by_op["create"]["roles"] == ["admin", "member"]
    assert by_op["delete"]["row_rule"] == "owner"


async def test_upsert_updates_an_existing_slot_instead_of_duplicating(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)
    await _upsert(client, project_id, _entry(entity_id, "list", roles=["admin"]))

    response = await _upsert(client, project_id, _entry(entity_id, "list", roles=["member"]))

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["roles"] == ["member"]


async def test_upsert_leaves_slots_not_in_the_payload_alone(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)
    await _upsert(client, project_id, _entry(entity_id, "list"))

    response = await _upsert(client, project_id, _entry(entity_id, "get"))

    assert {p["operation"] for p in response.json()} == {"list", "get"}


async def test_duplicate_slots_in_one_request_are_rejected(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)

    response = await _upsert(
        client, project_id, _entry(entity_id, "list"), _entry(entity_id, "list")
    )

    assert response.status_code == 422
    assert response.json()["details"][0]["code"] == "duplicate"


async def test_unknown_role_is_rejected(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)

    response = await _upsert(client, project_id, _entry(entity_id, roles=["ghost"]))

    assert response.status_code == 422
    assert "ghost" in response.text
    assert (await client.get(f"/projects/{project_id}/permissions")).json()["total"] == 0


async def test_entity_from_another_project_is_rejected(client: AsyncClient) -> None:
    project_id, _ = await _setup(client)
    other_project = await make_project(client, "Other")
    foreign_entity = await make_entity(client, other_project)

    response = await _upsert(client, project_id, _entry(foreign_entity))

    assert response.status_code == 422
    assert "does not belong" in response.text


async def test_one_bad_entry_saves_nothing(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)

    response = await _upsert(
        client, project_id, _entry(entity_id, "list"), _entry(entity_id, "get", roles=["ghost"])
    )

    assert response.status_code == 422
    assert (await client.get(f"/projects/{project_id}/permissions")).json()["total"] == 0


async def test_custom_filter_rules(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)

    missing = await _upsert(client, project_id, _entry(entity_id, row_rule="custom_filter"))
    stray = await _upsert(client, project_id, _entry(entity_id, custom_filter_field="status"))
    valid = await _upsert(
        client,
        project_id,
        _entry(
            entity_id,
            row_rule="custom_filter",
            custom_filter_field="status",
            custom_filter_value="published",
        ),
    )

    assert missing.status_code == stray.status_code == 422
    assert valid.status_code == 200, valid.text
    assert valid.json()[0]["custom_filter_value"] == "published"


@pytest.mark.parametrize("operation", ["everything", "", "LIST", "drop"])
async def test_unknown_operations_are_rejected(client: AsyncClient, operation: str) -> None:
    project_id, entity_id = await _setup(client)

    response = await _upsert(client, project_id, _entry(entity_id, operation))

    assert response.status_code == 422


async def test_unknown_row_rule_is_rejected(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)

    response = await _upsert(client, project_id, _entry(entity_id, row_rule="everyone"))

    assert response.status_code == 422


async def test_empty_payload_is_rejected(client: AsyncClient) -> None:
    project_id, _ = await _setup(client)

    response = await client.post(f"/projects/{project_id}/permissions", json={"permissions": []})

    assert response.status_code == 422


async def test_get_patch_delete_one_permission(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)
    permission = (await _upsert(client, project_id, _entry(entity_id, "list"))).json()[0]

    fetched = await client.get(f"/permissions/{permission['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["entity_id"] == entity_id

    patched = await client.patch(
        f"/permissions/{permission['id']}", json={"roles": ["member"], "row_rule": "role_scoped"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["roles"] == ["member"]
    assert patched.json()["row_rule"] == "role_scoped"

    bad_role = await client.patch(f"/permissions/{permission['id']}", json={"roles": ["ghost"]})
    assert bad_role.status_code == 422

    assert (await client.delete(f"/permissions/{permission['id']}")).status_code == 204
    assert (await client.get(f"/permissions/{permission['id']}")).status_code == 404


async def test_list_is_paginated(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)
    await _upsert(
        client, project_id, *(_entry(entity_id, op) for op in ("list", "get", "create", "update"))
    )

    page = (await client.get(f"/projects/{project_id}/permissions", params={"limit": 3})).json()
    rest = (
        await client.get(f"/projects/{project_id}/permissions", params={"limit": 3, "offset": 3})
    ).json()

    assert page["total"] == rest["total"] == 4
    assert len(page["items"]) == 3 and len(rest["items"]) == 1


async def test_permissions_are_removed_with_their_entity(client: AsyncClient) -> None:
    project_id, entity_id = await _setup(client)
    permission = (await _upsert(client, project_id, _entry(entity_id))).json()[0]

    assert (await client.delete(f"/entities/{entity_id}")).status_code == 204

    assert (await client.get(f"/permissions/{permission['id']}")).status_code == 404


async def test_missing_things_are_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (
        await client.post(
            f"/projects/{missing}/permissions",
            json={"permissions": [_entry(str(missing))]},
        )
    ).status_code == 404
    assert (await client.get(f"/projects/{missing}/permissions")).status_code == 404
    assert (await client.get(f"/permissions/{missing}")).status_code == 404
    assert (await client.patch(f"/permissions/{missing}", json={"roles": []})).status_code == 404
    assert (await client.delete(f"/permissions/{missing}")).status_code == 404
