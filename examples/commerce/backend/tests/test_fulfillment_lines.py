"""Smoke test for FulfillmentLine (generated)."""
import uuid as _uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """This entity has access rules, so its smoke test signs in as a user who holds every role."""
    return authed_client


async def test_fulfillment_lines_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_fulfillment_lines(client)
    item_id = created["id"]

    response = await client.get(f"/fulfillment_lines/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/fulfillment_lines/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    assert (await client.head(f"/fulfillment_lines/{item_id}")).status_code == 200
    assert (await client.head(f"/fulfillment_lines/{_uuid.uuid4()}")).status_code == 404

    listing = await client.get("/fulfillment_lines")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/fulfillment_lines", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    invalid = await client.post("/fulfillment_lines", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"

    new_value = _factories.sample_fulfillment_lines()["quantity"]
    patched = await client.patch(f"/fulfillment_lines/{item_id}", json={"quantity": new_value})
    assert patched.status_code == 200, patched.text
    assert patched.json()["quantity"] == new_value

    replacement = await _factories.payload_fulfillment_lines(client, fulfillment_id=created["fulfillment_id"], order_line_id=created["order_line_id"])
    replaced = await client.put(f"/fulfillment_lines/{item_id}", json=replacement)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == item_id

    assert (await client.delete(f"/fulfillment_lines/{item_id}")).status_code == 204
    assert (await client.get(f"/fulfillment_lines/{item_id}")).status_code == 404
