"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import datetime as _dt
import random as _random
import string as _string
import typing as _t
import uuid as _uuid

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_authors() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "bio": "sample text " + _token(6),
        "born_on": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
        "rating": round(_random.uniform(0, 5), 2),
    }


async def payload_authors(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_authors()
    payload.update(overrides)
    return payload


async def make_authors(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/authors", json=await payload_authors(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_books() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "isbn": _token(12),
        "pages": _random.randint(1, 1001),
        "price": str(round(_random.uniform(0, 1000), 2)),
        "status": 'draft',
        "published_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "in_stock": True,
        "extra": {"key": "value"},
        "catalog_id": str(_uuid.uuid4()),
    }


async def payload_books(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_books()
    if "author_id" not in overrides:
        payload["author_id"] = (await make_authors(client))["id"]
    payload.update(overrides)
    return payload


async def make_books(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/books", json=await payload_books(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_members() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "email": _token(12),
        "joined_on": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
    }


async def payload_members(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_members()
    payload.update(overrides)
    return payload


async def make_members(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/members", json=await payload_members(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_profiles() -> dict[str, _t.Any]:
    return {
        "bio": "sample text " + _token(6),
    }


async def payload_profiles(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_profiles()
    if "member_id" not in overrides:
        payload["member_id"] = (await make_members(client))["id"]
    payload.update(overrides)
    return payload


async def make_profiles(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/profiles", json=await payload_profiles(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_shelves() -> dict[str, _t.Any]:
    return {
        "label": _token(12),
    }


async def payload_shelves(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_shelves()
    payload.update(overrides)
    return payload


async def make_shelves(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/shelves", json=await payload_shelves(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
