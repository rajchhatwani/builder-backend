"""B3-9 API: request_dependency approval flow, isolation, roles."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.dependency_policy import DependencyRequest
from app.models.platform import AuditLog
from app.services.dependency_policy_service import DependencyPolicyService
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

H = "sha256:" + "b" * 64


def _body(**kw: object) -> dict[str, object]:
    body: dict[str, object] = {"package": "Left_Pad", "version": "1.2.3", "reason": "need padding", "hashes": [H]}
    body.update(kw)
    return body


async def test_policy_lists_curated_and_allow_list(client: AsyncClient) -> None:
    pid = await make_project(client)
    p = (await client.get(f"/projects/{pid}/dependencies")).json()
    assert "web-core" in p["curated_sets"] and "orjson" in p["allow_list"]
    assert p["approved"] == [] and p["pending_requests"] == 0


async def test_request_approve_flow_and_idempotence(client: AsyncClient) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/dependencies"
    r = await client.post(f"{base}/requests", json=_body())
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["package"] == "left-pad" and req["status"] == "pending" and req["hashes"] == [H]
    again = await client.post(f"{base}/requests", json=_body())
    assert again.status_code == 200 and again.json()["id"] == req["id"]
    assert (await client.get(f"{base}")).json()["approved"] == []  # pending is not usable
    ok = await client.post(
        f"{base}/requests/{req['id']}/approve",
        json={"package": "left_pad", "version": "1.2.3", "hashes": [H]},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["decided_by"]
    pol = (await client.get(base)).json()
    assert [(a["package"], a["version"], a["hashes"]) for a in pol["approved"]] == [("left-pad", "1.2.3", [H])]
    # decided requests cannot be decided again
    assert (await client.post(f"{base}/requests/{req['id']}/deny", json={})).status_code == 409


async def test_deny_and_new_version_needs_new_request(client: AsyncClient) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/dependencies"
    req = (await client.post(f"{base}/requests", json=_body())).json()
    d = await client.post(f"{base}/requests/{req['id']}/deny", json={"note": "no"})
    assert d.status_code == 200 and d.json()["status"] == "denied"
    assert (await client.get(base)).json()["approved"] == []
    new = await client.post(f"{base}/requests", json=_body(version="1.2.4"))
    assert new.status_code == 201 and new.json()["id"] != req["id"]


async def test_changed_or_missing_confirmation_is_refused(client: AsyncClient) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/dependencies"
    req = (await client.post(f"{base}/requests", json=_body())).json()
    url = f"{base}/requests/{req['id']}/approve"
    for bad in (
        {},
        {"package": "left-pad", "version": "1.2.4", "hashes": [H]},
        {"package": "other", "version": "1.2.3", "hashes": [H]},
        {"package": "left-pad", "version": "1.2.3", "hashes": []},
    ):
        assert (await client.post(url, json=bad)).status_code == 409, bad
    assert (await client.get(base)).json()["approved"] == []


async def test_stale_request_cannot_be_approved(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/dependencies"
    req = (await client.post(f"{base}/requests", json=_body())).json()
    async with session_factory() as s:
        await s.execute(
            update(DependencyRequest)
            .where(DependencyRequest.id == uuid.UUID(req["id"]))
            .values(created_at=DependencyRequest.created_at - timedelta(days=30))
        )
        await s.commit()
    r = await client.post(
        f"{base}/requests/{req['id']}/approve",
        json={"package": "left-pad", "version": "1.2.3", "hashes": [H]},
    )
    assert r.status_code == 409 and "dependency_request_stale" in r.text


async def test_hostile_and_already_allowed_requests(client: AsyncClient) -> None:
    pid = await make_project(client)
    url = f"/projects/{pid}/dependencies/requests"
    for bad in (
        _body(package="git+https://x/y"),
        _body(package="pkg[extra]"),
        _body(package="pаndas"),
        _body(version=">=1.0"),
        _body(version="1.*"),
        _body(hashes=["md5:abc"]),
        _body(package="https://evil/p.whl"),
        {**_body(), "extra": 1},
    ):
        assert (await client.post(url, json=bad)).status_code == 422, bad
    assert (await client.post(url, json=_body(package="orjson", version="3.10.0"))).status_code == 409


async def test_roles(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/dependencies"
    await add_to_project_org(pid, "ed@example.com")
    ed = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    await add_to_project_org(pid, "vi@example.com")
    vi = await client_for("vi@example.com")
    await add_to_project_org(pid, "vi@example.com")
    assert (await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})).status_code == 201
    assert (await client.post(f"/projects/{pid}/members", json={"email": "vi@example.com", "role": "viewer"})).status_code == 201
    assert (await vi.get(base)).status_code == 200
    assert (await vi.get(f"{base}/requests")).status_code == 200
    assert (await vi.post(f"{base}/requests", json=_body())).status_code == 403
    req = await ed.post(f"{base}/requests", json=_body())
    assert req.status_code == 201
    rid = req.json()["id"]
    ok = {"package": "left-pad", "version": "1.2.3", "hashes": [H]}
    assert (await ed.post(f"{base}/requests/{rid}/approve", json=ok)).status_code == 403
    assert (await ed.post(f"{base}/requests/{rid}/deny", json={})).status_code == 403
    assert (await vi.post(f"{base}/requests/{rid}/approve", json=ok)).status_code == 403
    assert (await client.post(f"{base}/requests/{rid}/approve", json=ok)).status_code == 200


async def test_isolation_between_projects_and_orgs(client: AsyncClient, client_for: ClientFor) -> None:
    pid = await make_project(client)
    other = await make_project(client, "Other")
    req = (await client.post(f"/projects/{pid}/dependencies/requests", json=_body())).json()
    ok = {"package": "left-pad", "version": "1.2.3", "hashes": [H]}
    # same request id through another project of the same owner: not found, no approval leaks
    assert (await client.post(f"/projects/{other}/dependencies/requests/{req['id']}/approve", json=ok)).status_code == 404
    assert (await client.get(f"/projects/{other}/dependencies/requests")).json() == []
    eve = await client_for("eve@example.com")
    assert (await eve.get(f"/projects/{pid}/dependencies")).status_code == 404
    assert (await eve.get(f"/projects/{pid}/dependencies/requests")).status_code == 404
    assert (await eve.post(f"/projects/{pid}/dependencies/requests", json=_body())).status_code == 404
    assert (await eve.post(f"/projects/{pid}/dependencies/requests/{req['id']}/approve", json=ok)).status_code == 404
    assert (await client.get(f"/projects/{pid}/dependencies/requests")).json()[0]["status"] == "pending"


async def _approved(client: AsyncClient, pid: str) -> tuple[str, str]:
    base = f"/projects/{pid}/dependencies"
    req = (await client.post(f"{base}/requests", json=_body())).json()
    ok = {"package": "left-pad", "version": "1.2.3", "hashes": [H]}
    r = await client.post(f"{base}/requests/{req['id']}/approve", json=ok)
    assert r.status_code == 200 and r.json()["expires_at"]
    return base, req["id"]


async def test_revoke_owner_only_audited_and_blocks_again(
    client: AsyncClient, client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    base, rid = await _approved(client, pid)
    svc_line = f"left-pad==1.2.3 --hash={H}"
    async with session_factory() as s:
        assert (await DependencyPolicyService(s).check(uuid.UUID(pid), svc_line)).ok
    await add_to_project_org(pid, "ed@example.com")
    ed = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})
    assert (await ed.post(f"{base}/requests/{rid}/revoke", json={})).status_code == 403
    r = await client.post(f"{base}/requests/{rid}/revoke", json={"note": "cve"})
    assert r.status_code == 200 and r.json()["status"] == "revoked" and r.json()["revoked_at"]
    assert (await client.get(base)).json()["approved"] == []
    async with session_factory() as s:
        assert not (await DependencyPolicyService(s).check(uuid.UUID(pid), svc_line)).ok
        n = (
            await s.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == "dependency.revoke"))
        ).scalar_one()
        assert n == 1
    assert (await client.post(f"{base}/requests/{rid}/revoke", json={})).status_code == 409
    # a fresh request for the same pin is possible after revoke
    assert (await client.post(f"{base}/requests", json=_body())).status_code == 201


async def test_expired_approval_blocks_and_frees_the_slot(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    base, rid = await _approved(client, pid)
    async with session_factory() as s:
        await s.execute(
            update(DependencyRequest)
            .where(DependencyRequest.id == uuid.UUID(rid))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
        assert not (
            await DependencyPolicyService(s).check(uuid.UUID(pid), f"left-pad==1.2.3 --hash={H}")
        ).ok
    assert (await client.get(base)).json()["approved"] == []
    again = await client.post(f"{base}/requests", json=_body())
    assert again.status_code == 201 and again.json()["id"] != rid


async def test_ttl_is_configurable_and_hashes_required(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await make_project(client)
    base = f"/projects/{pid}/dependencies"
    nohash = (await client.post(f"{base}/requests", json=_body(hashes=[]))).json()
    r = await client.post(
        f"{base}/requests/{nohash['id']}/approve", json={"package": "left-pad", "version": "1.2.3"}
    )
    assert r.status_code == 409 and "dependency_hashes_required" in r.text
    monkeypatch.setattr(
        "app.services.dependency_policy_service.get_settings",
        lambda: Settings(environment="test", dependency_approval_ttl_days=1),
    )
    await client.post(f"{base}/requests/{nohash['id']}/deny", json={})
    req = (await client.post(f"{base}/requests", json=_body())).json()
    ok = await client.post(
        f"{base}/requests/{req['id']}/approve",
        json={"package": "left-pad", "version": "1.2.3", "hashes": [H]},
    )
    exp = datetime.fromisoformat(ok.json()["expires_at"])
    assert timedelta(hours=23) < exp - datetime.now(UTC) < timedelta(hours=25)
