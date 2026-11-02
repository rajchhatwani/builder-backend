"""CO3-4: expected_version on PUT /spec (409 when stale), 413 on oversize spec writes, advisor route."""

from httpx import AsyncClient

from tests.api.test_spec import build_blog


async def _version(client: AsyncClient, pid: str) -> int:
    return int((await client.get(f"/projects/{pid}")).json()["version"])


async def test_stale_expected_version_is_409_with_the_current_version(client: AsyncClient) -> None:
    pid = await build_blog(client)
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    current = await _version(client, pid)

    ok = await client.put(f"/projects/{pid}/spec", params={"expected_version": current}, json=spec)
    assert ok.status_code == 200, ok.text
    assert await _version(client, pid) == current + 1

    stale = await client.put(f"/projects/{pid}/spec", params={"expected_version": current}, json=spec)
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "version_conflict" and body["details"][0]["current_version"] == current + 1
    assert await _version(client, pid) == current + 1  # nothing was written

    legacy = await client.put(f"/projects/{pid}/spec", json=spec)  # no expected_version: still accepted
    assert legacy.status_code == 200


async def test_oversize_spec_write_is_413_even_when_chunked(client: AsyncClient) -> None:
    pid = await build_blog(client)
    big = b'{"x":"' + b"a" * (1024 * 1024 + 10) + b'"}'

    async def chunks():  # no Content-Length: only the bytes actually received count
        for i in range(0, len(big), 65536):
            yield big[i : i + 65536]

    for path in (f"/projects/{pid}/spec", f"/projects/{pid}/behavior/settings"):
        r = await client.put(path, content=chunks(), headers={"content-type": "application/json"})
        assert r.status_code == 413, (path, r.status_code)
        r2 = await client.put(path, content=big, headers={"content-type": "application/json"})
        assert r2.status_code == 413


async def test_advisor_is_read_only_project_gated_and_strict(client: AsyncClient) -> None:
    pid = await build_blog(client)
    r = await client.get(f"/projects/{pid}/advisor", params={"throughput_per_sec": 20000, "steps": 3, "needs_compensation": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["queue"]["recommended"] == "kafka" and body["workflow"]["recommended"] == "workflow"
    assert (await client.get(f"/projects/{pid}/advisor", params={"bogus": 1})).status_code == 422
    assert (await client.post(f"/projects/{pid}/advisor")).status_code == 405
    assert (await client.get("/projects/00000000-0000-0000-0000-000000000000/advisor")).status_code == 404
