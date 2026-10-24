"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_labels() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
    }


async def payload_labels(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_labels()
    payload.update(overrides)
    return payload


async def make_labels(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/labels", json=await payload_labels(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_tasks() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "done": True,
        "points": _random.randint(1, 1001),
    }


async def payload_tasks(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_tasks()
    payload.update(overrides)
    return payload


async def make_tasks(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/tasks", json=await payload_tasks(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
