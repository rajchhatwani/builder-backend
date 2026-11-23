"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_products() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "price_cents": _random.randint(1, 1001),
        "internal_cost": _random.randint(1, 1001),
    }


async def payload_products(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_products()
    payload.update(overrides)
    return payload


async def make_products(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/products", json=await payload_products(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_reviews() -> dict[str, _t.Any]:
    return {
        "stars": _random.randint(1, 1001),
        "body": _token(12),
    }


async def payload_reviews(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_reviews()
    payload.update(overrides)
    return payload


async def make_reviews(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/reviews", json=await payload_reviews(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
