"""M2 accept criteria: `GET spec` -> `PUT spec` on a new project round-trips to an
identical spec, `validate` reports the Blog model as clean, and invalid specs are
rejected in full without touching the project.
"""

from typing import Any

from httpx import AsyncClient


async def _make_entity(client: AsyncClient, project_id: str, name: str, **extra: Any) -> str:
    response = await client.post(f"/projects/{project_id}/entities", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _make_fields(client: AsyncClient, entity_id: str, fields: list[dict[str, Any]]) -> None:
    for field in fields:
        response = await client.post(f"/entities/{entity_id}/fields", json=field)
        assert response.status_code == 201, response.text


async def _make_relation(client: AsyncClient, project_id: str, **body: Any) -> None:
    response = await client.post(f"/projects/{project_id}/relations", json=body)
    assert response.status_code == 201, response.text


async def build_blog(client: AsyncClient, name: str = "Blog", slug: str | None = None) -> str:
    created = await client.post("/projects", json={"name": name, "slug": slug or "blog"})
    assert created.status_code == 201, created.text
    project_id = str(created.json()["id"])

    user = await _make_entity(client, project_id, "User")
    post = await _make_entity(
        client,
        project_id,
        "Post",
        options={"filterable": ["title", "published"], "sortable": ["title", "created_at"]},
    )
    comment = await _make_entity(client, project_id, "Comment")
    tag = await _make_entity(client, project_id, "Tag")

    await _make_fields(
        client,
        user,
        [
            {
                "name": "email",
                "type": "string",
                "required": True,
                "unique": True,
                "max_length": 255,
            },
            {"name": "display_name", "type": "string", "required": True, "max_length": 100},
            {
                "name": "role",
                "type": "enum",
                "enum_values": ["admin", "member"],
                "default": "member",
            },
        ],
    )
    await _make_fields(
        client,
        post,
        [
            {"name": "title", "type": "string", "required": True, "max_length": 200},
            {"name": "body", "type": "text", "required": True},
            {"name": "published", "type": "boolean", "required": True, "default": False},
            {"name": "views", "type": "integer", "min_value": 0, "default": 0},
        ],
    )
    await _make_fields(client, comment, [{"name": "body", "type": "text", "required": True}])
    await _make_fields(
        client,
        tag,
        [{"name": "name", "type": "string", "required": True, "unique": True, "max_length": 50}],
    )

    await _make_relation(
        client,
        project_id,
        kind="one_to_many",
        from_entity_id=user,
        to_entity_id=post,
        from_name="posts",
        to_name="author",
        on_delete="cascade",
        required=True,
    )
    await _make_relation(
        client,
        project_id,
        kind="one_to_many",
        from_entity_id=post,
        to_entity_id=comment,
        from_name="comments",
        to_name="post",
        on_delete="cascade",
        required=True,
    )
    await _make_relation(
        client,
        project_id,
        kind="many_to_many",
        from_entity_id=post,
        to_entity_id=tag,
        from_name="tags",
        to_name="posts",
    )
    return project_id


async def test_blog_model_validates_clean(client: AsyncClient) -> None:
    project_id = await build_blog(client)

    response = await client.post(f"/projects/{project_id}/validate")

    assert response.status_code == 200
    assert response.json() == {"valid": True, "issues": []}


async def test_spec_is_assembled_deterministically(client: AsyncClient) -> None:
    project_id = await build_blog(client)

    response = await client.get(f"/projects/{project_id}/spec")
    spec = response.json()

    assert response.status_code == 200
    assert spec["spec_version"] == 1
    assert spec["project"]["slug"] == "blog"
    assert [e["name"] for e in spec["entities"]] == ["Comment", "Post", "Tag", "User"]
    post = next(e for e in spec["entities"] if e["name"] == "Post")
    assert [f["name"] for f in post["fields"]] == ["title", "body", "published", "views"]
    assert post["table_name"] == "posts"
    assert [(r["from_entity"], r["from_name"]) for r in spec["relations"]] == [
        ("Post", "comments"),
        ("Post", "tags"),
        ("User", "posts"),
    ]
    assert (await client.get(f"/projects/{project_id}/spec")).json() == spec


async def test_spec_round_trip_into_new_project_is_identical(client: AsyncClient) -> None:
    source_id = await build_blog(client)
    spec = (await client.get(f"/projects/{source_id}/spec")).json()
    target = await client.post("/projects", json={"name": "Copy", "slug": "copy"})
    target_id = target.json()["id"]

    put = await client.put(f"/projects/{target_id}/spec", json=spec)
    assert put.status_code == 200, put.text
    round_tripped = (await client.get(f"/projects/{target_id}/spec")).json()

    # Project identity (name, slug) belongs to the project, not to the imported model.
    assert round_tripped["project"] == {**spec["project"], "name": "Copy", "slug": "copy"}
    assert {k: v for k, v in round_tripped.items() if k != "project"} == {
        k: v for k, v in spec.items() if k != "project"
    }
    assert put.json() == round_tripped
    validation = await client.post(f"/projects/{target_id}/validate")
    assert validation.json()["valid"] is True


async def test_put_spec_replaces_existing_model(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    spec["entities"] = [e for e in spec["entities"] if e["name"] == "Tag"]
    spec["relations"] = []

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 200, put.text
    entities = (await client.get(f"/projects/{project_id}/entities")).json()
    assert [e["name"] for e in entities["items"]] == ["Tag"]
    relations = (await client.get(f"/projects/{project_id}/relations")).json()
    assert relations["total"] == 0


async def test_put_spec_bumps_project_version(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    before = (await client.get(f"/projects/{project_id}")).json()["version"]
    spec = (await client.get(f"/projects/{project_id}/spec")).json()

    await client.put(f"/projects/{project_id}/spec", json=spec)

    assert (await client.get(f"/projects/{project_id}")).json()["version"] == before + 1


async def test_put_invalid_spec_returns_all_issues_and_changes_nothing(
    client: AsyncClient,
) -> None:
    project_id = await build_blog(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    before = spec
    bad = {**spec, "entities": [dict(e) for e in spec["entities"]]}
    bad["entities"][0]["fields"] = [{"name": 'x"; import os', "type": "text"}]
    bad["entities"][1]["fields"] = [{"name": "class", "type": "nope"}]
    bad["relations"] = [{**bad["relations"][0], "to_entity": "Ghost"}]

    put = await client.put(f"/projects/{project_id}/spec", json=bad)

    assert put.status_code == 422
    body = put.json()
    assert body["code"] == "spec_invalid"
    found = {(d["path"], d["code"]) for d in body["details"]}
    assert ("entities[0].fields[0].name", "invalid_identifier") in found
    assert ("entities[1].fields[0].name", "reserved_word") in found
    assert ("entities[1].fields[0].type", "unknown_type") in found
    assert ("relations[0].to_entity", "unknown_entity") in found
    assert (await client.get(f"/projects/{project_id}/spec")).json() == before


async def test_put_spec_rejects_unknown_keys(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    spec["entities"][0]["surprise"] = True

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 422
    assert put.json()["code"] == "validation_error"


async def test_validate_reports_problems_in_stored_model(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    entities = (await client.get(f"/projects/{project_id}/entities")).json()["items"]
    user = next(e for e in entities if e["name"] == "User")
    await client.patch(f"/entities/{user['id']}", json={"table_name": "user"})

    response = await client.post(f"/projects/{project_id}/validate")

    body = response.json()
    assert response.status_code == 200
    assert body["valid"] is False
    assert [(i["code"]) for i in body["issues"]] == ["reserved_word"]
    assert body["issues"][0]["path"].endswith(".table_name")


async def test_spec_endpoints_404_for_unknown_project(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    spec = {"project": {"name": "x", "slug": "x"}}

    assert (await client.get(f"/projects/{missing}/spec")).status_code == 404
    assert (await client.put(f"/projects/{missing}/spec", json=spec)).status_code == 404
    assert (await client.post(f"/projects/{missing}/validate")).status_code == 404
