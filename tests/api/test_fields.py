import uuid

from httpx import AsyncClient


async def _create_entity(client: AsyncClient) -> str:
    project = await client.post("/projects", json={"name": "Blog"})
    project_id = project.json()["id"]
    entity = await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    entity_id: str = entity.json()["id"]
    return entity_id


async def test_create_field_auto_assigns_position(client: AsyncClient) -> None:
    entity_id = await _create_entity(client)

    first = await client.post(
        f"/entities/{entity_id}/fields", json={"name": "title", "type": "string"}
    )
    assert first.status_code == 201
    assert first.json()["position"] == 0

    second = await client.post(
        f"/entities/{entity_id}/fields", json={"name": "body", "type": "text"}
    )
    assert second.status_code == 201
    assert second.json()["position"] == 1


async def test_create_field_on_missing_entity_404s(client: AsyncClient) -> None:
    response = await client.post(
        f"/entities/{uuid.uuid4()}/fields", json={"name": "title", "type": "string"}
    )
    assert response.status_code == 404


async def test_duplicate_field_name_conflicts(client: AsyncClient) -> None:
    entity_id = await _create_entity(client)
    await client.post(f"/entities/{entity_id}/fields", json={"name": "title", "type": "string"})
    response = await client.post(
        f"/entities/{entity_id}/fields", json={"name": "title", "type": "text"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_update_and_delete_field(client: AsyncClient) -> None:
    entity_id = await _create_entity(client)
    create = await client.post(
        f"/entities/{entity_id}/fields", json={"name": "title", "type": "string"}
    )
    field_id = create.json()["id"]

    update = await client.patch(f"/fields/{field_id}", json={"required": True, "max_length": 200})
    assert update.status_code == 200
    assert update.json()["required"] is True
    assert update.json()["max_length"] == 200

    delete = await client.delete(f"/fields/{field_id}")
    assert delete.status_code == 204


async def test_list_fields_ordered_by_position(client: AsyncClient) -> None:
    entity_id = await _create_entity(client)
    await client.post(f"/entities/{entity_id}/fields", json={"name": "title", "type": "string"})
    await client.post(f"/entities/{entity_id}/fields", json={"name": "body", "type": "text"})

    response = await client.get(f"/entities/{entity_id}/fields")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [f["name"] for f in body["items"]] == ["title", "body"]
