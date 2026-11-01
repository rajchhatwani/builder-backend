"""Smoke test for Invoice (generated)."""
import uuid as _uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """This entity has access rules, so its smoke test signs in as a user who holds every role."""
    return authed_client


async def test_invoices_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_invoices(client)
    item_id = created["id"]

    response = await client.get(f"/invoices/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/invoices/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    assert (await client.head(f"/invoices/{item_id}")).status_code == 200
    assert (await client.head(f"/invoices/{_uuid.uuid4()}")).status_code == 404

    listing = await client.get("/invoices")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/invoices", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    filtered = await client.get("/invoices", params={"status": created["status"]})
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [item_id]

    invalid = await client.post("/invoices", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"

    # A number the column cannot store is a 422, never a 500.
    too_big = await client.post(
        "/invoices", json=await _factories.payload_invoices(client, amount=10**30)
    )
    assert too_big.status_code == 422, too_big.text
    assert too_big.json()["code"] == "validation_error"

    new_value = _factories.sample_invoices()["invoice_no"]
    patched = await client.patch(f"/invoices/{item_id}", json={"invoice_no": new_value})
    assert patched.status_code == 200, patched.text
    assert patched.json()["invoice_no"] == new_value

    replacement = await _factories.payload_invoices(client, supplier_id=created["supplier_id"])
    replaced = await client.put(f"/invoices/{item_id}", json=replacement)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == item_id

    assert (await client.delete(f"/invoices/{item_id}")).status_code == 204
    assert (await client.get(f"/invoices/{item_id}")).status_code == 404
