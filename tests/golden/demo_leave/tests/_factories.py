"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import datetime as _dt
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_employees() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "email": _token(12),
        "department": _token(12),
        "leave_balance": _random.randint(0, 1000),
    }


async def payload_employees(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_employees()
    payload.update(overrides)
    return payload


async def make_employees(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/employees", json=await payload_employees(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_leave_requests() -> dict[str, _t.Any]:
    return {
        "start_date": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
        "end_date": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
        "days": _random.randint(1, 60),
        "balance": _random.randint(0, 1000),
        "reason": _token(12),
    }


async def payload_leave_requests(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_leave_requests()
    if "employee_id" not in overrides:
        payload["employee_id"] = (await make_employees(client))["id"]
    payload.update(overrides)
    return payload


async def make_leave_requests(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/leave_requests", json=await payload_leave_requests(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
