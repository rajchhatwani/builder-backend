"""CP-6E: upgrade proposals and scorecard routes."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import upgrade_engine as ue
from app.core.generator.base import FileTree
from app.models.generation import Generation
from app.models.platform import AuditLog
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_spec import build_blog

MISSING = str(uuid.uuid4())


@pytest.fixture
def newer_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the generator moved on: one generated file changes and one block gets a patch bump."""
    import app.services.upgrade_service as svc

    real = svc.generate

    def changed(spec: object) -> FileTree:
        tree = real(spec)  # type: ignore[arg-type]
        tree["app/main.py"] = tree["app/main.py"] + "# generator 1.0.1\n"
        return tree

    versions = svc.current_block_versions()
    bumped = {**versions, "crud": "9.9.9"} if "crud" in versions else {**versions, next(iter(versions)): "9.9.9"}
    monkeypatch.setattr(svc, "generate", changed)
    monkeypatch.setattr(svc, "current_block_versions", lambda: bumped)


async def _generated(client: AsyncClient) -> str:
    pid = await build_blog(client)
    r = await client.get(f"/projects/{pid}/generate/download")
    assert r.status_code == 200, r.text
    return pid


async def test_no_baseline_is_409(client: AsyncClient) -> None:
    pid = await build_blog(client)
    r = await client.post(f"/projects/{pid}/upgrades")
    assert r.status_code == 409 and r.json()["code"] == "no_baseline", r.text


async def test_up_to_date_is_409(client: AsyncClient) -> None:
    pid = await _generated(client)
    r = await client.post(f"/projects/{pid}/upgrades")
    assert r.status_code == 409 and r.json()["code"] == "up_to_date", r.text
    assert (await client.get(f"/projects/{pid}/upgrades")).json()["total"] == 0


async def test_download_stores_the_base(client: AsyncClient, session_factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
    pid = await _generated(client)
    async with session_factory() as s:
        gen = (await s.execute(select(Generation).where(Generation.project_id == uuid.UUID(pid)))).scalar_one()
        blob = (await s.execute(text("select file_blob from generations where id = :i"), {"i": gen.id})).scalar_one()
        tree = ue.decode_blob(bytes(blob))
    assert gen.generator_version == ue.GENERATOR_VERSION and gen.block_versions
    assert "app/main.py" in tree and not any(p.startswith(("app/hooks/", "app/custom")) for p in tree)


async def test_create_list_get_patch_dismiss(client: AsyncClient, newer_generator: None) -> None:
    pid = await _generated(client)
    r = await client.post(f"/projects/{pid}/upgrades")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "open" and p["to_generator_version"] == ue.GENERATOR_VERSION
    assert p["files"] == [{"path": "app/main.py", "zone": "generated", "change": "modified"}]
    assert p["block_changes"][0]["to"] == "9.9.9" and p["block_changes"][0]["bump"] == "major"
    assert p["auto_apply_eligible"] is False  # a major bump never qualifies
    assert p["patch_size"] > 0 and p["scorecard"]["checks"] and "kept" in p
    assert set(p["sbom_diff"]) == {"added", "removed", "changed"}

    listed = (await client.get(f"/projects/{pid}/upgrades")).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == p["id"] and "files" not in listed["items"][0]
    got = await client.get(f"/projects/{pid}/upgrades/{p['id']}")
    assert got.status_code == 200 and got.json()["id"] == p["id"]

    patch = await client.get(f"/projects/{pid}/upgrades/{p['id']}/patch")
    assert patch.status_code == 200 and patch.headers["content-type"].startswith("text/x-diff")
    assert patch.text.startswith("diff --git a/app/main.py b/app/main.py\n") and "+# generator 1.0.1" in patch.text

    # a second open proposal for the same base generation is refused, and names the open one
    again = await client.post(f"/projects/{pid}/upgrades")
    assert again.status_code == 409 and again.json()["code"] == "proposal_open"
    assert again.json()["details"][0]["proposal_id"] == p["id"]

    done = await client.post(f"/projects/{pid}/upgrades/{p['id']}/dismiss")
    assert done.status_code == 200 and done.json()["status"] == "dismissed" and done.json()["decided_at"]
    for action in ("dismiss", "applied"):
        r2 = await client.post(f"/projects/{pid}/upgrades/{p['id']}/{action}")
        assert r2.status_code == 409 and r2.json()["code"] == "proposal_closed"
    # once decided, a new proposal can be opened for the same base
    assert (await client.post(f"/projects/{pid}/upgrades")).status_code == 201


async def test_mark_applied_and_audit(client: AsyncClient, newer_generator: None, session_factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
    pid = await _generated(client)
    p = (await client.post(f"/projects/{pid}/upgrades")).json()
    r = await client.post(f"/projects/{pid}/upgrades/{p['id']}/applied")
    assert r.status_code == 200 and r.json()["status"] == "applied"
    async with session_factory() as s:
        actions = {a for (a,) in (await s.execute(select(AuditLog.action).where(AuditLog.project_id == uuid.UUID(pid)))).all()}
    assert {"upgrade.proposal_create", "upgrade.proposal_applied"} <= actions


async def test_unknown_proposal_is_404(client: AsyncClient) -> None:
    pid = await _generated(client)
    for suffix in ("", "/patch"):
        assert (await client.get(f"/projects/{pid}/upgrades/{MISSING}{suffix}")).status_code == 404
    assert (await client.post(f"/projects/{pid}/upgrades/{MISSING}/dismiss")).status_code == 404


async def test_viewer_reads_but_cannot_write(client: AsyncClient, client_for: ClientFor, newer_generator: None) -> None:
    pid = await _generated(client)
    p = (await client.post(f"/projects/{pid}/upgrades")).json()
    viewer = await client_for("viewer@example.com")
    await add_to_project_org(pid, "viewer@example.com")
    assert (await client.post(f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"})).status_code == 201
    base = f"/projects/{pid}"
    assert (await viewer.get(f"{base}/scorecard")).status_code == 200
    assert (await viewer.get(f"{base}/upgrades")).status_code == 200
    assert (await viewer.get(f"{base}/upgrades/{p['id']}")).status_code == 200
    assert (await viewer.get(f"{base}/upgrades/{p['id']}/patch")).status_code == 200
    for path in ("/upgrades", f"/upgrades/{p['id']}/dismiss", f"/upgrades/{p['id']}/applied"):
        r = await viewer.post(base + path)
        assert r.status_code == 403, (path, r.text)
    assert (await client.get(f"{base}/upgrades/{p['id']}")).json()["status"] == "open"


async def test_other_tenant_project_is_404(client: AsyncClient, client_for: ClientFor, newer_generator: None) -> None:
    pid = await _generated(client)
    p = (await client.post(f"/projects/{pid}/upgrades")).json()
    other = await client_for("stranger@example.com")
    base = f"/projects/{pid}"
    for method, path in (
        ("GET", "/scorecard"), ("GET", "/upgrades"), ("POST", "/upgrades"), ("GET", f"/upgrades/{p['id']}"),
        ("GET", f"/upgrades/{p['id']}/patch"), ("POST", f"/upgrades/{p['id']}/dismiss"), ("POST", f"/upgrades/{p['id']}/applied"),
    ):
        r = await other.request(method, base + path)
        assert r.status_code == 404, (method, path, r.status_code)


async def test_proposal_of_another_projects_generation_is_not_used(client: AsyncClient, client_for: ClientFor, newer_generator: None) -> None:
    """The base is always the project's own latest generation: a project with none gets no_baseline even
    when another project (another user) has one, and a foreign proposal id answers 404."""
    a = await _generated(client)
    p = (await client.post(f"/projects/{a}/upgrades")).json()
    b = await make_project(client, "Second")
    r = await client.post(f"/projects/{b}/upgrades")
    assert r.status_code == 409 and r.json()["code"] == "no_baseline"
    assert (await client.get(f"/projects/{b}/upgrades/{p['id']}")).status_code == 404
    assert (await client.post(f"/projects/{b}/upgrades/{p['id']}/dismiss")).status_code == 404


async def test_generation_without_stored_tree_gives_baseline_unavailable(client: AsyncClient, session_factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
    pid = await _generated(client)
    async with session_factory() as s:
        await s.execute(text("update generations set file_blob = null where project_id = :p"), {"p": uuid.UUID(pid)})
        await s.commit()
    r = await client.post(f"/projects/{pid}/upgrades")
    assert r.status_code == 409 and r.json()["code"] == "baseline_unavailable"


async def test_corrupt_or_bomb_blob_is_refused(client: AsyncClient, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[type-arg]
    pid = await _generated(client)
    async with session_factory() as s:
        await s.execute(text("update generations set file_blob = :b where project_id = :p"), {"b": b"garbage", "p": uuid.UUID(pid)})
        await s.commit()
    r = await client.post(f"/projects/{pid}/upgrades")
    assert r.status_code == 409 and r.json()["code"] == "baseline_unreadable"
    monkeypatch.setattr(ue, "MAX_BLOB_BYTES", 100)
    async with session_factory() as s:
        await s.execute(text("update generations set file_blob = :b where project_id = :p"), {"b": ue.encode_blob({"a.txt": "x" * 100_000}), "p": uuid.UUID(pid)})
        await s.commit()
    r = await client.post(f"/projects/{pid}/upgrades")
    assert r.status_code == 409 and r.json()["code"] == "baseline_too_large"


async def test_scorecard_route_shape_and_fixes(client: AsyncClient) -> None:
    pid = await build_blog(client)
    never = (await client.get(f"/projects/{pid}/scorecard")).json()
    ids = {c["id"]: c for c in never["checks"]}
    assert 0 <= never["score"] <= 100 and isinstance(never["passing"], bool)
    assert ids["drift.spec"]["status"] == "warn" and ids["drift.spec"]["fix"]["action"] == "regenerate"
    assert ids["security.auth_enabled"]["status"] == "fail"  # the blog has no auth block
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200
    after = {c["id"]: c for c in (await client.get(f"/projects/{pid}/scorecard")).json()["checks"]}
    assert after["drift.spec"]["status"] == "pass" and after["block_version_lag"]["status"] == "pass"
    assert after["dependency_freshness"]["status"] == "pass"


async def test_scorecard_drift_after_spec_edit(client: AsyncClient) -> None:
    pid = await _generated(client)
    r = await client.post(f"/projects/{pid}/entities", json={"name": "Extra"})
    assert r.status_code == 201, r.text
    ids = {c["id"]: c for c in (await client.get(f"/projects/{pid}/scorecard")).json()["checks"]}
    assert ids["drift.spec"]["status"] == "warn"
