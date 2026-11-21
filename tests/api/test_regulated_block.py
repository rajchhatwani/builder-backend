"""CP-6B: GET / PUT /projects/{id}/behavior/regulated: versions, stale edit (409), removal, refusal."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_project


async def test_regulated_block_get_put_and_conflict(client: AsyncClient) -> None:
    pid = await make_project(client)
    url = f"/projects/{pid}/behavior/regulated"
    first = (await client.get(url)).json()
    assert first["version"] == 0 and first["regulated"] is None

    block = {"enabled": False, "key_provider": "command", "fields": []}
    put = await client.put(url, json={"regulated": block, "expected_version": 0})
    assert put.status_code == 200, put.text
    assert put.json()["regulated"] == block and put.json()["version"] == 1
    assert (await client.get(url)).json()["regulated"] == block
    assert (await client.get(f"/projects/{pid}/spec")).json()["regulated"] == block

    stale = await client.put(url, json={"regulated": None, "expected_version": 0})
    assert stale.status_code == 409, stale.text

    gone = await client.put(url, json={"regulated": None, "expected_version": 1})
    assert gone.status_code == 200 and gone.json()["regulated"] is None


async def test_regulated_block_refuses_unknown_keys(client: AsyncClient) -> None:
    pid = await make_project(client)
    bad = {"enabled": False, "nope": 1}
    r = await client.put(f"/projects/{pid}/behavior/regulated", json={"regulated": bad, "expected_version": 0})
    assert r.status_code == 422, r.text
