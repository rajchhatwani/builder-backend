"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_sellers() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
    }


async def payload_sellers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_sellers()
    payload.update(overrides)
    return payload


async def make_sellers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/sellers", json=await payload_sellers(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
