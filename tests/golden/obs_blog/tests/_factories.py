"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_comments() -> dict[str, _t.Any]:
    return {
        "body": "sample text " + _token(6),
    }


async def payload_comments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_comments()
    if "post_id" not in overrides:
        payload["post_id"] = (await make_posts(client))["id"]
    payload.update(overrides)
    return payload


async def make_comments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/comments", json=await payload_comments(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_posts() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "body": "sample text " + _token(6),
        "published": True,
        "views": _random.randint(0, 1000),
    }


async def payload_posts(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_posts()
    if "author_id" not in overrides:
        payload["author_id"] = (await make_users(client))["id"]
    payload.update(overrides)
    return payload


async def make_posts(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/posts", json=await payload_posts(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_tags() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
    }


async def payload_tags(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_tags()
    payload.update(overrides)
    return payload


async def make_tags(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/tags", json=await payload_tags(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_users() -> dict[str, _t.Any]:
    return {
        "email": _token(12),
        "display_name": _token(12),
        "role": 'admin',
    }


async def payload_users(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_users()
    payload.update(overrides)
    return payload


async def make_users(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/users", json=await payload_users(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
