"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_leave_requests() -> dict[str, _t.Any]:
    return {
        "employee": _token(12),
        "days": _random.randint(1, 1001),
        "balance": _random.randint(1, 1001),
    }


async def payload_leave_requests(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_leave_requests()
    payload.update(overrides)
    return payload


async def make_leave_requests(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/leave_requests", json=await payload_leave_requests(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
