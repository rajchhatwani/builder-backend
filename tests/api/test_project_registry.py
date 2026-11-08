"""B3-8 API tests: the project registry (blocks, hooks, dependencies): append-only, owner-only writes, org isolation."""

import uuid

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

H = "a" * 64


async def test_registry_blocks_hooks_deps_append_only(client: AsyncClient) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/registry"
    blk = {"name": "auth", "version": "1.0.0", "content_hash": H}
    assert (await client.post(f"{base}/blocks", json=blk)).status_code == 201
    assert (await client.post(f"{base}/blocks", json=blk)).status_code == 200  # idempotent
    clash = await client.post(f"{base}/blocks", json={**blk, "content_hash": "b" * 64})
    assert clash.status_code == 409 and clash.json()["code"] == "block_version_immutable"
    assert (await client.post(f"{base}/blocks", json={**blk, "content_hash": "xyz"})).status_code == 422
    assert len((await client.get(f"{base}/blocks")).json()) == 1

    hook = {"hook_name": "on_order", "content_hash": H, "author": "run:42"}
    h1 = await client.post(f"{base}/hooks", json=hook)
    assert h1.status_code == 201 and h1.json()["approved_by"] is None
    assert (await client.post(f"{base}/hooks", json=hook)).status_code == 200
    await client.post(f"{base}/hooks", json={**hook, "content_hash": "c" * 64})
    assert len((await client.get(f"{base}/hooks")).json()) == 2  # history kept, not overwritten
    ok = await client.post(f"{base}/hooks/{h1.json()['id']}/approve")
    assert ok.status_code == 200 and ok.json()["approved_by"] == str(client.user.id)  # type: ignore[attr-defined]
    again = await client.post(f"{base}/hooks/{h1.json()['id']}/approve")
    assert again.status_code == 409
    assert (await client.post(f"{base}/hooks/{uuid.uuid4()}/approve")).status_code == 404

    dep = {"package": "httpx", "version": "0.28.1", "hash": "sha256:abc"}
    assert (await client.post(f"{base}/deps", json=dep)).status_code == 201
    assert (await client.post(f"{base}/deps", json=dep)).status_code == 200
    bad = await client.post(f"{base}/deps", json={**dep, "hash": "sha256:other"})
    assert bad.status_code == 409
    assert len((await client.get(f"{base}/deps")).json()) == 1

    await _org_view(client, pid)


async def _org_view(client: AsyncClient, pid: str) -> None:
    orgs = (await client.get("/orgs")).json()
    items = orgs["items"] if isinstance(orgs, dict) else orgs
    slug = items[0]["slug"] if "slug" in items[0] else items[0]["organization"]["slug"]
    rows = (await client.get(f"/orgs/{slug}/registry/projects")).json()
    row = next(r for r in rows if r["project_id"] == pid)
    assert (row["block_versions"], row["hooks"], row["hooks_unapproved"], row["dependencies"]) == (
        1,
        2,
        1,
        1,
    )


async def test_registry_writes_are_owner_only_reads_open_to_members(
    client: AsyncClient, client_for: ClientFor
) -> None:
    pid = await make_project(client)
    await add_to_project_org(pid, "ed@example.com")
    ed = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    r = await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})
    assert r.status_code == 201, r.text
    base = f"/projects/{pid}/registry"
    assert (await ed.get(f"{base}/hooks")).status_code == 200
    hook = {"hook_name": "h", "content_hash": H, "author": "a"}
    assert (await ed.post(f"{base}/hooks", json=hook)).status_code == 403
    assert (await ed.post(f"{base}/deps", json={"package": "p", "version": "1", "hash": "h"})).status_code == 403


async def test_registry_isolated_between_orgs(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await make_project(client)
    await client.post(
        f"/projects/{pid}/registry/hooks", json={"hook_name": "h", "content_hash": H, "author": "a"}
    )
    eve = await client_for("eve@example.com")
    assert (await eve.get(f"/projects/{pid}/registry/hooks")).status_code == 404
    assert (
        await eve.post(
            f"/projects/{pid}/registry/hooks",
            json={"hook_name": "h2", "content_hash": H, "author": "e"},
        )
    ).status_code == 404


async def test_hook_approval_is_owner_only_and_recorded(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/registry"
    h = (await client.post(f"{base}/hooks", json={"hook_name": "h", "content_hash": H, "author": "run:1"})).json()
    await add_to_project_org(pid, "ed@example.com")
    ed = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    r = await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})
    assert r.status_code == 201, r.text
    assert (await ed.post(f"{base}/hooks/{h['id']}/approve")).status_code == 403
    still = next(x for x in (await client.get(f"{base}/hooks")).json() if x["id"] == h["id"])
    assert still["approved_by"] is None  # the refused approval changed nothing


async def test_hook_of_another_project_cannot_be_approved_through_this_one(client: AsyncClient) -> None:
    a = await make_project(client)
    b = await make_project(client)
    h = (await client.post(f"/projects/{a}/registry/hooks", json={"hook_name": "h", "content_hash": H, "author": "x"})).json()
    assert (await client.post(f"/projects/{b}/registry/hooks/{h['id']}/approve")).status_code == 404
    row = (await client.get(f"/projects/{a}/registry/hooks")).json()[0]
    assert row["approved_by"] is None


async def test_registry_refuses_malformed_entries(client: AsyncClient) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/registry"
    for bad_hash in ("", "a" * 63, "g" * 64):
        r = await client.post(f"{base}/blocks", json={"name": "x", "version": "1", "content_hash": bad_hash})
        assert r.status_code == 422, bad_hash
    assert (await client.post(f"{base}/blocks", json={"version": "1", "content_hash": H})).status_code == 422
    assert (await client.get(f"{base}/blocks")).json() == []
