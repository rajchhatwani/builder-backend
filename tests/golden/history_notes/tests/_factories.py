"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_notes() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "body": "sample text " + _token(6),
        "payload": {"key": "value"},
        "private_note": "sample text " + _token(6),
    }


async def payload_notes(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_notes()
    payload.update(overrides)
    return payload


async def make_notes(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/notes", json=await payload_notes(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_tickets() -> dict[str, _t.Any]:
    return {
        "subject": _token(12),
        "assignee": _token(12),
        "internal_memo": "sample text " + _token(6),
    }


async def payload_tickets(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_tickets()
    payload.update(overrides)
    return payload


async def make_tickets(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/tickets", json=await payload_tickets(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
