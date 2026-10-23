"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_orders() -> dict[str, _t.Any]:
    return {
        "total": str(round(_random.uniform(1, 100000), 2)),
        "status": 'pending',
    }


async def payload_orders(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_orders()
    payload.update(overrides)
    return payload


async def make_orders(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/orders", json=await payload_orders(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
