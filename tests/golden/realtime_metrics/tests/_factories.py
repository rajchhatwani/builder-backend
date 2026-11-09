"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import datetime as _dt
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_expenses() -> dict[str, _t.Any]:
    return {
        "category": _token(12),
        "amount": str(round(_random.uniform(0, 1000), 2)),
        "qty": _random.randint(1, 1001),
        "rate": round(_random.uniform(0, 1000), 2),
        "paid": True,
        "cost_basis": str(round(_random.uniform(0, 1000), 2)),
        "spent_on": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
        "logged_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "code": _token(12),
    }


async def payload_expenses(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_expenses()
    payload.update(overrides)
    return payload


async def make_expenses(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/expenses", json=await payload_expenses(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_payrolls() -> dict[str, _t.Any]:
    return {
        "person": _token(12),
        "salary": str(round(_random.uniform(0, 1000), 2)),
    }


async def payload_payrolls(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_payrolls()
    payload.update(overrides)
    return payload


async def make_payrolls(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/payrolls", json=await payload_payrolls(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
