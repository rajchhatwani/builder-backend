"""Smoke test for Note (generated)."""
import uuid as _uuid

from httpx import AsyncClient

from tests import _factories


async def test_notes_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_notes(client)
    item_id = created["id"]

    response = await client.get(f"/notes/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/notes/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    assert (await client.head(f"/notes/{item_id}")).status_code == 200
    assert (await client.head(f"/notes/{_uuid.uuid4()}")).status_code == 404

    listing = await client.get("/notes")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/notes", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    invalid = await client.post("/notes", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"

    new_value = _factories.sample_notes()["title"]
    patched = await client.patch(f"/notes/{item_id}", json={"title": new_value})
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == new_value

    replacement = await _factories.payload_notes(client)
    replaced = await client.put(f"/notes/{item_id}", json=replacement)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == item_id

    assert (await client.delete(f"/notes/{item_id}")).status_code == 204
    assert (await client.get(f"/notes/{item_id}")).status_code == 404
