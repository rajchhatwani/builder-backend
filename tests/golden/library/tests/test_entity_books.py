"""Smoke test for Book (generated)."""
import uuid as _uuid

from httpx import AsyncClient

from tests import _factories


async def test_books_crud_flow(client: AsyncClient) -> None:
    created = await _factories.make_books(client)
    item_id = created["id"]

    response = await client.get(f"/books/{item_id}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == item_id

    missing = await client.get(f"/books/{_uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    assert (await client.head(f"/books/{item_id}")).status_code == 200
    assert (await client.head(f"/books/{_uuid.uuid4()}")).status_code == 404

    listing = await client.get("/books")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["id"] for item in listing.json()["items"]] == [item_id]

    bad_sort = await client.get("/books", params={"sort": "__no_such_field__"})
    assert bad_sort.status_code == 422
    assert bad_sort.json()["code"] == "invalid_sort"

    filtered = await client.get("/books", params={"in_stock": created["in_stock"]})
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [item_id]

    searched = await client.get("/books", params={"q": created["isbn"]})
    assert searched.status_code == 200, searched.text
    assert [item["id"] for item in searched.json()["items"]] == [item_id]

    invalid = await client.post("/books", json={})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"

    # A number the column cannot store is a 422, never a 500.
    too_big = await client.post(
        "/books", json=await _factories.payload_books(client, pages=10**30)
    )
    assert too_big.status_code == 422, too_big.text
    assert too_big.json()["code"] == "validation_error"

    new_value = _factories.sample_books()["title"]
    patched = await client.patch(f"/books/{item_id}", json={"title": new_value})
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == new_value

    replacement = await _factories.payload_books(client, author_id=created["author_id"])
    replaced = await client.put(f"/books/{item_id}", json=replacement)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == item_id

    assert (await client.delete(f"/books/{item_id}")).status_code == 204
    assert (await client.get(f"/books/{item_id}")).status_code == 404
