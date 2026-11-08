import uuid

from httpx import AsyncClient

from tests.api.conftest import ClientFor


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


async def test_parallel_updates_with_same_version_have_one_winner(client: AsyncClient) -> None:
    """FEAT F-1: optimistic locking must be atomic (was 3-4 winners out of 8)."""
    import asyncio

    for round_no in range(3):
        project_id = (await client.post("/projects", json={"name": f"Race {round_no}"})).json()["id"]
        results = await asyncio.gather(
            *[
                client.patch(f"/projects/{project_id}", json={"version": 1, "description": f"w{i}"})
                for i in range(8)
            ]
        )
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 7, codes
        final = (await client.get(f"/projects/{project_id}")).json()
        assert final["version"] == 2
        assert final["updated_at"] > final["created_at"]  # the CAS update still bumps updated_at


async def test_same_name_in_two_tenants_both_succeed(
    client: AsyncClient, client_for: ClientFor
) -> None:
    """FEAT F-2: no cross-tenant slug collision / existence oracle."""
    other = await client_for("other-tenant@example.com")
    a = await client.post("/projects", json={"name": "Shared Name"})
    b = await other.post("/projects", json={"name": "Shared Name"})
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["slug"] == b.json()["slug"] == "shared-name"


async def test_derived_slug_is_suffixed_within_an_org_explicit_one_conflicts(
    client: AsyncClient,
) -> None:
    first = await client.post("/projects", json={"name": "Blog"})
    second = await client.post("/projects", json={"name": "Blog"})
    third = await client.post("/projects", json={"name": "Blog"})
    assert [first.json()["slug"], second.json()["slug"], third.json()["slug"]] == [
        "blog",
        "blog-2",
        "blog-3",
    ]
    dup = await client.post("/projects", json={"name": "Other", "slug": "blog"})
    assert dup.status_code == 409


async def test_non_ascii_names_do_not_collide(client: AsyncClient) -> None:
    one = await client.post("/projects", json={"name": "日本語"})
    two = await client.post("/projects", json={"name": "🚀🚀"})
    assert one.status_code == 201 and two.status_code == 201
    assert one.json()["slug"] != two.json()["slug"]
