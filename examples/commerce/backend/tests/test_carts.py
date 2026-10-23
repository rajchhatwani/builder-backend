"""Smoke test for Cart (generated)."""
import uuid as _uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """This entity has access rules, so its smoke test signs in as a user who holds every role."""
    return authed_client


async def test_carts_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_carts(client)
    item_id = created["id"]

    response = await client.get(f"/carts/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/carts/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    assert (await client.head(f"/carts/{item_id}")).status_code == 200
    assert (await client.head(f"/carts/{_uuid.uuid4()}")).status_code == 404

    listing = await client.get("/carts")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/carts", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    filtered = await client.get("/carts", params={"status": created["status"]})
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [item_id]

    invalid = await client.post("/carts", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"

    new_value = _factories.sample_carts()["token"]
    patched = await client.patch(f"/carts/{item_id}", json={"token": new_value})
    assert patched.status_code == 200, patched.text
    assert patched.json()["token"] == new_value

    replacement = await _factories.payload_carts(client)
    replaced = await client.put(f"/carts/{item_id}", json=replacement)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == item_id

    assert (await client.delete(f"/carts/{item_id}")).status_code == 204
    assert (await client.get(f"/carts/{item_id}")).status_code == 404
