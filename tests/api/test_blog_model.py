"""Builds the Blog model from PLAN.md section 1 step 1 through the Builder API:
User, Post, Comment entities with fields, a one-to-many (User -> Post, Post ->
Comment) and a many-to-many (Post <-> Tag). This is the concrete proof behind
M1's accept criterion: "Postman can build the Blog model fully."
"""

from httpx import AsyncClient


async def test_build_blog_model_end_to_end(client: AsyncClient) -> None:
    project = await client.post("/projects", json={"name": "Blog"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    user = await client.post(f"/projects/{project_id}/entities", json={"name": "User"})
    post = await client.post(f"/projects/{project_id}/entities", json={"name": "Post"})
    comment = await client.post(f"/projects/{project_id}/entities", json={"name": "Comment"})
    tag = await client.post(f"/projects/{project_id}/entities", json={"name": "Tag"})
    for response in (user, post, comment, tag):
        assert response.status_code == 201
    user_id, post_id, comment_id, tag_id = (
        user.json()["id"],
        post.json()["id"],
        comment.json()["id"],
        tag.json()["id"],
    )

    user_fields = [
        {"name": "email", "type": "string", "required": True, "unique": True, "max_length": 255},
        {"name": "display_name", "type": "string", "required": True, "max_length": 100},
    ]
    post_fields = [
        {"name": "title", "type": "string", "required": True, "max_length": 200},
        {"name": "body", "type": "text", "required": True},
        {"name": "published", "type": "boolean", "required": True, "default": False},
    ]
    comment_fields = [
        {"name": "body", "type": "text", "required": True},
    ]
    tag_fields = [
        {"name": "name", "type": "string", "required": True, "unique": True, "max_length": 50},
    ]
    for entity_id, fields in (
        (user_id, user_fields),
        (post_id, post_fields),
        (comment_id, comment_fields),
        (tag_id, tag_fields),
    ):
        for field in fields:
            response = await client.post(f"/entities/{entity_id}/fields", json=field)
            assert response.status_code == 201, response.text

    user_posts_relation = await client.post(
        f"/projects/{project_id}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": user_id,
            "to_entity_id": post_id,
            "from_name": "posts",
            "to_name": "author",
            "on_delete": "cascade",
            "required": True,
        },
    )
    post_comments_relation = await client.post(
        f"/projects/{project_id}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": post_id,
            "to_entity_id": comment_id,
            "from_name": "comments",
            "to_name": "post",
            "on_delete": "cascade",
            "required": True,
        },
    )
    post_tags_relation = await client.post(
        f"/projects/{project_id}/relations",
        json={
            "kind": "many_to_many",
            "from_entity_id": post_id,
            "to_entity_id": tag_id,
            "from_name": "tags",
            "to_name": "posts",
        },
    )
    for response in (user_posts_relation, post_comments_relation, post_tags_relation):
        assert response.status_code == 201, response.text

    entities_response = await client.get(f"/projects/{project_id}/entities")
    assert entities_response.json()["total"] == 4

    relations_response = await client.get(f"/projects/{project_id}/relations")
    relations_body = relations_response.json()
    assert relations_body["total"] == 3
    kinds = sorted(r["kind"] for r in relations_body["items"])
    assert kinds == ["many_to_many", "one_to_many", "one_to_many"]

    post_fields_response = await client.get(f"/entities/{post_id}/fields")
    assert post_fields_response.json()["total"] == 3
