"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_items() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "price": round(_random.uniform(0, 1000), 2),
    }


async def payload_items(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_items()
    payload.update(overrides)
    return payload


async def make_items(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/items", json=await payload_items(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
