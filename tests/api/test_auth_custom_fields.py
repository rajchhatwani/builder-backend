import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project


def _field(name: str = "nickname", type_: str = "string", **extra: Any) -> dict[str, Any]:
    return {"name": name, "label": name.title(), "type": type_, **extra}


async def _create(client: AsyncClient, project_id: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.post(
        f"/projects/{project_id}/auth/custom-fields", json=_field(**kwargs)
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_string_field_with_constraints(client: AsyncClient) -> None:
    project_id = await make_project(client)

    body = await _create(
        client, project_id, required=True, unique=True, min_length=2, max_length=30
    )

    assert body["name"] == "nickname"
    assert body["type"] == "string"
    assert body["required"] is True and body["unique"] is True
    assert (body["min_length"], body["max_length"]) == (2, 30)
    assert (await client.get(f"/auth/custom-fields/{body['id']}")).json() == body


async def test_create_each_type(client: AsyncClient) -> None:
    project_id = await make_project(client)
    cases: dict[str, dict[str, Any]] = {
        "bio": {"type_": "text"},
        "age": {"type_": "integer", "min_value": 0, "max_value": 150},
        "score": {"type_": "float", "min_value": 0.5},
        "newsletter": {"type_": "boolean", "default_value": "false"},
        "birthday": {"type_": "date"},
        "seen_at": {"type_": "datetime"},
        "work_email": {"type_": "email"},
        "mobile": {"type_": "phone"},
        "website": {"type_": "url"},
        "plan": {"type_": "enum", "enum_values": ["free", "pro"], "default_value": "free"},
    }

    for name, kwargs in cases.items():
        body = await _create(client, project_id, name=name, **kwargs)
        assert body["name"] == name

    listing = (await client.get(f"/projects/{project_id}/auth/custom-fields")).json()
    assert listing["total"] == len(cases)


@pytest.mark.parametrize("name", ["Nick", "1nick", "nick-name", "nick name", 'a"; drop', ""])
async def test_names_must_be_lowercase_identifiers(client: AsyncClient, name: str) -> None:
    project_id = await make_project(client)

    response = await client.post(
        f"/projects/{project_id}/auth/custom-fields", json=_field(name=name)
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "name",
    [
        "id",
        "email",
        "phone",
        "password",
        "password_hash",
        "roles",
        "is_active",
        "email_verified_at",
        "phone_verified_at",
        "last_login_at",
        "deleted_at",
        "created_at",
        "updated_at",
        "role",
        "tenant_id",
    ],
)
async def test_names_used_by_the_generated_user_table_are_reserved(
    client: AsyncClient, name: str
) -> None:
    """The builder must refuse what generation would refuse, so the error comes early."""
    project_id = await make_project(client)

    response = await client.post(
        f"/projects/{project_id}/auth/custom-fields", json=_field(name=name)
    )

    assert response.status_code == 409, response.text
    assert "reserved" in response.json()["message"]


async def test_duplicate_name_conflicts(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await _create(client, project_id)

    response = await client.post(f"/projects/{project_id}/auth/custom-fields", json=_field())

    assert response.status_code == 409


async def test_same_name_in_another_project_is_fine(client: AsyncClient) -> None:
    first = await make_project(client, "One")
    second = await make_project(client, "Two")

    await _create(client, first)
    await _create(client, second)


@pytest.mark.parametrize(
    "bad",
    [
        {"type_": "enum"},  # needs values
        {"type_": "enum", "enum_values": []},
        {"type_": "string", "enum_values": ["a"]},  # values only for enums
        {"type_": "integer", "max_length": 5},  # length only for text-like
        {"type_": "string", "min_value": 1},  # range only for numbers
        {"type_": "string", "min_length": 9, "max_length": 3},
        {"type_": "integer", "min_value": 9, "max_value": 3},
        {"type_": "string", "max_length": 0},
        {"type_": "blob"},
    ],
)
async def test_type_and_constraint_coherence(client: AsyncClient, bad: dict[str, Any]) -> None:
    project_id = await make_project(client)
    kwargs = dict(bad)
    payload = _field(type_=kwargs.pop("type_"), **kwargs)

    response = await client.post(f"/projects/{project_id}/auth/custom-fields", json=payload)

    assert response.status_code == 422, response.text


async def test_positions_are_assigned_in_creation_order(client: AsyncClient) -> None:
    project_id = await make_project(client)
    first = await _create(client, project_id, name="aaa")
    second = await _create(client, project_id, name="bbb")
    third = await _create(client, project_id, name="ccc")

    assert first["position"] < second["position"] < third["position"]
    listing = (await client.get(f"/projects/{project_id}/auth/custom-fields")).json()
    assert [f["name"] for f in listing["items"]] == ["aaa", "bbb", "ccc"]


async def test_patch_updates_constraints_but_not_name_or_type(client: AsyncClient) -> None:
    project_id = await make_project(client)
    field = await _create(client, project_id, max_length=20)

    response = await client.patch(
        f"/auth/custom-fields/{field['id']}",
        json={
            "label": "Handle",
            "required": True,
            "max_length": 40,
            "name": "other",
            "type": "text",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "Handle"
    assert body["required"] is True
    assert body["max_length"] == 40
    assert body["name"] == "nickname"
    assert body["type"] == "string"


async def test_delete_field(client: AsyncClient) -> None:
    project_id = await make_project(client)
    field = await _create(client, project_id)

    assert (await client.delete(f"/auth/custom-fields/{field['id']}")).status_code == 204

    assert (await client.get(f"/auth/custom-fields/{field['id']}")).status_code == 404
    assert (await client.get(f"/projects/{project_id}/auth/custom-fields")).json()["total"] == 0


async def test_fields_are_removed_with_their_project(client: AsyncClient) -> None:
    project_id = await make_project(client)
    field = await _create(client, project_id)

    await client.delete(f"/projects/{project_id}")

    assert (await client.get(f"/auth/custom-fields/{field['id']}")).status_code == 404


async def test_list_is_paginated(client: AsyncClient) -> None:
    project_id = await make_project(client)
    for name in ("aaa", "bbb", "ccc"):
        await _create(client, project_id, name=name)

    page = (
        await client.get(f"/projects/{project_id}/auth/custom-fields", params={"limit": 2})
    ).json()

    assert page["total"] == 3 and len(page["items"]) == 2


async def test_missing_things_are_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (
        await client.post(f"/projects/{missing}/auth/custom-fields", json=_field())
    ).status_code == 404
    assert (await client.get(f"/projects/{missing}/auth/custom-fields")).status_code == 404
    assert (await client.get(f"/auth/custom-fields/{missing}")).status_code == 404
    assert (
        await client.patch(f"/auth/custom-fields/{missing}", json={"label": "x"})
    ).status_code == 404
    assert (await client.delete(f"/auth/custom-fields/{missing}")).status_code == 404
