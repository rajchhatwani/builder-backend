"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_secrets() -> dict[str, _t.Any]:
    return {
        "label": _token(12),
    }


async def payload_secrets(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_secrets()
    payload.update(overrides)
    return payload


async def make_secrets(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/secrets", json=await payload_secrets(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
