"""Smoke test for Shelf (generated)."""
import uuid as _uuid

from httpx import AsyncClient

from tests import _factories


async def test_shelves_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_shelves(client)
    item_id = created["id"]

    response = await client.get(f"/shelves/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/shelves/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    listing = await client.get("/shelves")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/shelves", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    filtered = await client.get("/shelves", params={"label": created["label"]})
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [item_id]

    invalid = await client.post("/shelves", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
