"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import datetime as _dt
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_invoices() -> dict[str, _t.Any]:
    return {
        "amount": str(round(_random.uniform(0, 1000), 2)),
        "po_amount": str(round(_random.uniform(0, 1000), 2)),
        "due_date": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
        "memo": _token(12),
    }


async def payload_invoices(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_invoices()
    if "supplier_id" not in overrides:
        payload["supplier_id"] = (await make_suppliers(client))["id"]
    payload.update(overrides)
    return payload


async def make_invoices(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/invoices", json=await payload_invoices(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_suppliers() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "email": _token(12),
        "payment_terms": _token(12),
        "active": True,
    }


async def payload_suppliers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_suppliers()
    payload.update(overrides)
    return payload


async def make_suppliers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/suppliers", json=await payload_suppliers(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
