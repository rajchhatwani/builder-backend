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


def sample_deals() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
    }


async def payload_deals(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_deals()
    payload.update(overrides)
    return payload


async def make_deals(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/deals", json=await payload_deals(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
