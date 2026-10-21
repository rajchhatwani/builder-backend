import uuid

from httpx import AsyncClient


async def test_create_and_get_project(client: AsyncClient) -> None:
    response = await client.post("/projects", json={"name": "Blog"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Blog"
    assert body["slug"] == "blog"
    assert body["version"] == 1

    get_response = await client.get(f"/projects/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]


async def test_create_project_with_explicit_slug(client: AsyncClient) -> None:
    response = await client.post("/projects", json={"name": "Blog", "slug": "my-blog"})
    assert response.status_code == 201
    assert response.json()["slug"] == "my-blog"


async def test_create_project_duplicate_slug_conflicts(client: AsyncClient) -> None:
    await client.post("/projects", json={"name": "Blog", "slug": "blog"})
    response = await client.post("/projects", json={"name": "Blog Two", "slug": "blog"})
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_get_missing_project_404s(client: AsyncClient) -> None:
    response = await client.get(f"/projects/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_update_project_requires_matching_version(client: AsyncClient) -> None:
    create = await client.post("/projects", json={"name": "Blog"})
    project_id = create.json()["id"]

    stale_update = await client.patch(
        f"/projects/{project_id}", json={"version": 999, "name": "New Name"}
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "conflict"

    good_update = await client.patch(
        f"/projects/{project_id}", json={"version": 1, "name": "New Name"}
    )
    assert good_update.status_code == 200
    assert good_update.json()["name"] == "New Name"
    assert good_update.json()["version"] == 2


async def test_list_projects_paginates(client: AsyncClient) -> None:
    for i in range(3):
        await client.post("/projects", json={"name": f"Project {i}"})

    response = await client.get("/projects", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_delete_project(client: AsyncClient) -> None:
    create = await client.post("/projects", json={"name": "Blog"})
    project_id = create.json()["id"]

    delete_response = await client.delete(f"/projects/{project_id}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/projects/{project_id}")
    assert get_response.status_code == 404
