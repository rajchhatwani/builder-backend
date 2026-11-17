"""Smoke test for DiscountUsage (generated)."""
import uuid as _uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """This entity has access rules, so its smoke test signs in as a user who holds every role."""
    return authed_client


async def test_discount_usages_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_discount_usages(client)
    item_id = created["id"]

    response = await client.get(f"/discount_usages/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/discount_usages/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    listing = await client.get("/discount_usages")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/discount_usages", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    invalid = await client.post("/discount_usages", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
