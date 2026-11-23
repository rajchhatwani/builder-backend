"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import datetime as _dt
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_appointments() -> dict[str, _t.Any]:
    return {
        "scheduled_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "reason": _token(12),
        "status": 'booked',
    }


async def payload_appointments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_appointments()
    payload.update(overrides)
    return payload


async def make_appointments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/appointments", json=await payload_appointments(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_patients() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "dob": _token(12),
        "phone": _token(12),
        "postcode": _token(10),
        "age": _random.randint(1, 1001),
        "notes": "sample text " + _token(6),
        "insurance_no": _token(12),
    }


async def payload_patients(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_patients()
    payload.update(overrides)
    return payload


async def make_patients(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/patients", json=await payload_patients(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
