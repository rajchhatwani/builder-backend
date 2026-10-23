"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import random as _random
import string as _string
import typing as _t

from httpx import AsyncClient

from tests.storage_support import upload_ok


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_photos() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "image_id": None,
        "thumbnail_id": None,
    }


async def payload_photos(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_photos()
    if "image_id" not in overrides:
        payload["image_id"] = (await upload_ok(client))["id"]  # a real, scanned file
    payload.update(overrides)
    return payload


async def make_photos(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/photos", json=await payload_photos(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
