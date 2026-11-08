"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_customers() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "email": _token(12),
        "api_token": _token(12),
    }


async def payload_customers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_customers()
    payload.update(overrides)
    return payload


async def make_customers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/customers", json=await payload_customers(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_orders() -> dict[str, _t.Any]:
    return {
        "reference": _token(12),
        "total": str(round(_random.uniform(0, 1000), 2)),
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
