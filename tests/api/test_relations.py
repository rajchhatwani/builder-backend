import uuid

from httpx import AsyncClient


async def _create_project_with_entities(client: AsyncClient) -> tuple[str, str, str]:
    project = await client.post("/projects", json={"name": "Blog"})
    project_id = project.json()["id"]
    post = await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    tag = await client.post(f"/projects/{project_id}/entities", json={"name": "Tag"})
    return project_id, post.json()["id"], tag.json()["id"]


async def test_create_relation_happy_path(client: AsyncClient) -> None:
    project_id, post_id, tag_id = await _create_project_with_entities(client)
    response = await client.post(
        f"/projects/{project_id}/relations",
        json={
            "kind": "many_to_many",
            "from_entity_id": post_id,
            "to_entity_id": tag_id,
            "from_name": "tags",
            "to_name": "posts",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "many_to_many"
    assert body["on_delete"] == "restrict"


async def test_create_relation_on_missing_project_404s(client: AsyncClient) -> None:
    response = await client.post(
        f"/projects/{uuid.uuid4()}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": str(uuid.uuid4()),
            "to_entity_id": str(uuid.uuid4()),
            "from_name": "items",
            "to_name": "parent",
        },
    )
    assert response.status_code == 404


async def test_create_relation_with_entity_outside_project_400s(client: AsyncClient) -> None:
    project_id, post_id, _tag_id = await _create_project_with_entities(client)
    other_project = await client.post("/projects", json={"name": "Other"})
    other_entity = await client.post(
        f"/projects/{other_project.json()['id']}/entities", json={"name": "Thing"}
    )

    response = await client.post(
        f"/projects/{project_id}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": post_id,
            "to_entity_id": other_entity.json()["id"],
            "from_name": "things",
            "to_name": "post",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_reference"


async def test_duplicate_relation_conflicts(client: AsyncClient) -> None:
    project_id, post_id, tag_id = await _create_project_with_entities(client)
    payload = {
        "kind": "many_to_many",
        "from_entity_id": post_id,
        "to_entity_id": tag_id,
        "from_name": "tags",
        "to_name": "posts",
    }
    await client.post(f"/projects/{project_id}/relations", json=payload)
    response = await client.post(f"/projects/{project_id}/relations", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_update_and_delete_relation(client: AsyncClient) -> None:
    project_id, post_id, tag_id = await _create_project_with_entities(client)
    create = await client.post(
        f"/projects/{project_id}/relations",
        json={
            "kind": "many_to_many",
            "from_entity_id": post_id,
            "to_entity_id": tag_id,
            "from_name": "tags",
            "to_name": "posts",
        },
    )
    relation_id = create.json()["id"]

    update = await client.patch(f"/relations/{relation_id}", json={"on_delete": "cascade"})
    assert update.status_code == 200
    assert update.json()["on_delete"] == "cascade"

    delete = await client.delete(f"/relations/{relation_id}")
    assert delete.status_code == 204
