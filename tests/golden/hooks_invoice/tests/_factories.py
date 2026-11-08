"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_invoices() -> dict[str, _t.Any]:
    return {
        "invoice_no": _token(12),
        "amount": str(round(_random.uniform(0, 1000), 2)),
        "po_amount": str(round(_random.uniform(0, 1000), 2)),
    }


async def payload_invoices(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_invoices()
    payload.update(overrides)
    return payload


async def make_invoices(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/invoices", json=await payload_invoices(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
