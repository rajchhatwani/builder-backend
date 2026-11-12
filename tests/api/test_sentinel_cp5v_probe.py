"""SENTINEL CP-5V probes: one hostile input per new route (admin operations, usage limits, reindex)."""

import subprocess

import pytest
from httpx import AsyncClient

from app.core import crypto, platform_security as sec
from app.core.key_provider import KeyRing
from app.models.enums import PlatformRole
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor
from tests.api.test_admin_operations import _admin, _org
from tests.api.test_behavior_blocks import add_to_project_org


async def test_limit_value_hostile_inputs(client: AsyncClient, client_for: ClientFor) -> None:
    await _org(client)
    ops = await _admin(client_for)
    url = "/admin/organizations/acme/usage/limits/imports.rows"
    for bad in (-1, 1.5, "abc", [1], {"a": 1}, float("inf") if False else "1e400"):
        assert (await ops.put(url, json={"limit_value": bad})).status_code == 422, bad
    assert (await ops.put(url, content=b'{"limit_value": NaN}', headers={"content-type": "application/json"})).status_code == 422
    # SQL-ish metric / org keys are bound parameters, never interpolated
    assert (await ops.put("/admin/organizations/acme/usage/limits/x';DROP TABLE usage_limits;--", json={"limit_value": 1})).status_code in (400, 404, 422)
    assert (await ops.get("/admin/organizations/' OR '1'='1/usage")).status_code == 404
    assert (await ops.get("/admin/organizations/acme/usage")).status_code == 200  # table intact
    # beyond BIGINT must be refused cleanly, not 500
    r = await ops.put(url, json={"limit_value": 2**63})
    assert r.status_code == 422, r.status_code


async def test_golive_never_spawns_or_connects(
    client_for: ClientFor, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = await _admin(client_for)

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("go-live must not shell out")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    r = await ops.post("/admin/operations/golive")
    assert r.status_code == 200
    text = r.text.lower()
    assert "fernet" not in text and "secret_key" not in text


async def test_operations_does_not_reload_key_provider_when_ring_is_cold(
    client_for: ClientFor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cold or failed ring makes _get_ring() call provider.load() (a subprocess for `command`)."""
    calls: list[int] = []

    class CommandKeyProvider:
        def load(self) -> KeyRing:
            calls.append(1)
            raise RuntimeError("would run the key command")

    monkeypatch.setattr(crypto, "_provider", CommandKeyProvider())
    monkeypatch.setattr(crypto, "_ring", None)
    ops = await _admin(client_for)
    r = await ops.get("/admin/operations")
    assert r.status_code == 200
    assert r.json()["key_provider"]["error"] == "not_loaded"
    assert calls == [], f"admin overview invoked the key provider {len(calls)} time(s)"


async def test_reindex_viewer_and_stranger_refused(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    pid = await make_project(owner)
    await add_to_project_org(pid, "viewer@example.com")
    assert (await owner.post(f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"})).status_code == 201
    assert (await viewer.post(f"/projects/{pid}/search/reindex")).status_code == 403
    assert (await stranger.post(f"/projects/{pid}/search/reindex")).status_code in (403, 404)
    assert (await owner.post(f"/projects/{pid}/search/reindex")).status_code == 200
    admin_audience = await client_for("ops2@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN)
    assert (await admin_audience.post(f"/projects/{pid}/search/reindex")).status_code in (401, 403, 404)
