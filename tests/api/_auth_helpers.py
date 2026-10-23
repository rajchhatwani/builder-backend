"""Shared builders for the auth API tests."""

from typing import Any

from httpx import AsyncClient

SMTP = {
    "host": "smtp.example.com",
    "port": 587,
    "use_tls": True,
    "from_email": "noreply@example.com",
    "from_name": "Example",
}


async def make_project(client: AsyncClient, name: str = "Shop") -> str:
    response = await client.post("/projects", json={"name": name})
    assert response.status_code == 201, response.text
    project_id: str = response.json()["id"]
    return project_id


def auth_body(**overrides: Any) -> dict[str, Any]:
    """A valid auth config: email magic link is on by default, so SMTP is included."""
    body: dict[str, Any] = {"smtp_config": SMTP, "app_url": "https://shop.example.com"}
    body.update(overrides)
    return body


async def make_auth(client: AsyncClient, project_id: str, **overrides: Any) -> dict[str, Any]:
    response = await client.post(f"/projects/{project_id}/auth", json=auth_body(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def make_role(
    client: AsyncClient, project_id: str, name: str, **extra: Any
) -> dict[str, Any]:
    payload = {"name": name, "label": name.title(), **extra}
    response = await client.post(f"/projects/{project_id}/roles", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def make_entity(client: AsyncClient, project_id: str, name: str = "Item") -> str:
    response = await client.post(f"/projects/{project_id}/entities", json={"name": name})
    assert response.status_code == 201, response.text
    entity_id: str = response.json()["id"]
    return entity_id
