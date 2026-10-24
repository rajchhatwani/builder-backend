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
    payload.update(overrides)
    return payload


async def make_comments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/comments", json=await payload_comments(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_documents() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "status": 'draft',
        "pages": _random.randint(1, 1001),
    }


async def payload_documents(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_documents()
    payload.update(overrides)
    return payload


async def make_documents(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/documents", json=await payload_documents(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
