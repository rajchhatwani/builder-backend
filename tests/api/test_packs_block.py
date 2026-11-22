"""CP-6F: GET / PUT /projects/{id}/behavior/packs: the packs block is stored, versioned and reaches the spec."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_project


async def test_packs_block_get_put_conflict_and_spec(client: AsyncClient) -> None:
    pid = await make_project(client)
    url = f"/projects/{pid}/behavior/packs"
    first = (await client.get(url)).json()
    assert first["version"] == 0 and first["packs"] is None

    block = {"money": {"ledger": {"read_roles": ["admin"], "post_roles": ["admin"]}, "currency": {"currencies": ["USD"]}}}
    put = await client.put(url, json={"packs": block, "expected_version": 0})
    assert put.status_code == 200, put.text
    assert put.json()["version"] == 1
    assert put.json()["packs"]["money"]["currency"]["currencies"] == ["USD"]
    assert (await client.get(f"/projects/{pid}/spec")).json()["packs"]["money"]["ledger"]["post_roles"] == ["admin"]

    stale = await client.put(url, json={"packs": None, "expected_version": 0})
    assert stale.status_code == 409, stale.text
    gone = await client.put(url, json={"packs": None, "expected_version": 1})
    assert gone.status_code == 200 and gone.json()["packs"] is None


async def test_packs_block_refuses_unknown_keys_and_empty_body(client: AsyncClient) -> None:
    pid = await make_project(client)
    url = f"/projects/{pid}/behavior/packs"
    bad = await client.put(url, json={"packs": {"money": {"ledger": {"nope": 1}}}, "expected_version": 0})
    assert bad.status_code == 422, bad.text
    empty = await client.put(url, json={"expected_version": 0})
    assert empty.status_code == 422 and empty.json()["code"] == "missing_block"
