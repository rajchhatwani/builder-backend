import uuid

from httpx import AsyncClient


async def _create_project(client: AsyncClient, name: str = "Blog") -> str:
    response = await client.post("/projects", json={"name": name})
    project_id: str = response.json()["id"]
    return project_id


async def test_create_entity_derives_table_name_and_plural_path(client: AsyncClient) -> None:
    project_id = await _create_project(client)
    response = await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    assert response.status_code == 201
    body = response.json()
    assert body["table_name"] == "post"
    assert body["plural_path"] == "posts"
    assert body["options"]["default_page_size"] == 20


async def test_create_entity_on_missing_project_404s(client: AsyncClient) -> None:
    response = await client.post(f"/projects/{uuid.uuid4()}/entities", json={"name": "Post"})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_duplicate_entity_name_conflicts(client: AsyncClient) -> None:
    project_id = await _create_project(client)
    await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    response = await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_get_missing_entity_404s(client: AsyncClient) -> None:
    response = await client.get(f"/entities/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_update_and_delete_entity(client: AsyncClient) -> None:
    project_id = await _create_project(client)
    create = await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    entity_id = create.json()["id"]

    update = await client.patch(f"/entities/{entity_id}", json={"table_name": "blog_posts"})
    assert update.status_code == 200
    assert update.json()["table_name"] == "blog_posts"

    delete = await client.delete(f"/entities/{entity_id}")
    assert delete.status_code == 204

    get_after_delete = await client.get(f"/entities/{entity_id}")
    assert get_after_delete.status_code == 404


async def test_list_entities_for_project(client: AsyncClient) -> None:
    project_id = await _create_project(client)
    for name in ("User", "Post", "Comment"):
        await client.post(f"/projects/{project_id}/entities", json={"name": name})

    response = await client.get(f"/projects/{project_id}/entities")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {e["name"] for e in body["items"]} == {"User", "Post", "Comment"}
