"""B2-11: the builder stores the single-object spec blocks (events, providers, notifications, jobs,
workflows, api_edge, webhooks, hook_effects): spec round trip, per-section get/put with versions,
409 on a stale edit, op-log undo/redo/restore, viewer denial, secrets refused."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.spec_models import Spec
from app.services.behavior_service import BLOCKS
from app.services.ops.canon import canonical_bytes
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"
NAMES = ("webhooks_orders", "workflows_orders", "notifications_orders", "combined_async")


def _fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def _blocks(spec: dict[str, Any]) -> dict[str, Any]:
    dumped = Spec.model_validate(spec).model_dump(mode="json")
    return {k: dumped[k] for k in BLOCKS if dumped[k] is not None}


async def _canon(client: AsyncClient, pid: str) -> bytes:
    r = await client.get(f"/projects/{pid}/spec")
    assert r.status_code == 200, r.text
    return canonical_bytes(Spec.model_validate(r.json()))


@pytest.mark.parametrize("name", NAMES)
async def test_spec_round_trip_keeps_the_blocks(client: AsyncClient, name: str) -> None:
    pid = await make_project(client)
    fixture = _fixture(name)
    put = await client.put(f"/projects/{pid}/spec", json=fixture)
    assert put.status_code == 200, put.text
    expected = _blocks(fixture)
    assert expected  # the fixture does exercise blocks
    for source in (put.json(), (await client.get(f"/projects/{pid}/spec")).json()):
        got = {k: source[k] for k in BLOCKS if source[k] is not None}
        assert got == expected
    # a second PUT of what GET returned changes nothing
    before = await _canon(client, pid)
    again = await client.put(f"/projects/{pid}/spec", json=(await client.get(f"/projects/{pid}/spec")).json())
    assert again.status_code == 200, again.text
    assert await _canon(client, pid) == before


@pytest.mark.parametrize("key", BLOCKS)
async def test_a_new_project_has_no_block(client: AsyncClient, key: str) -> None:
    pid = await make_project(client)
    body = (await client.get(f"/projects/{pid}/behavior/{key.replace('_', '-')}")).json()
    assert body["version"] == 0 and body[key] is None


async def test_per_section_get_put_versions_and_conflict(client: AsyncClient) -> None:
    pid = await make_project(client)
    await client.put(f"/projects/{pid}/spec", json=_fixture("combined_async"))
    base = f"/projects/{pid}/behavior"
    jobs = (await client.get(f"{base}/jobs")).json()
    assert jobs["jobs"] is not None and jobs["version"] == 1
    events_v = (await client.get(f"{base}/events")).json()["version"]
    saved = await client.put(f"{base}/jobs", json={"jobs": jobs["jobs"], "expected_version": 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2 and saved.json()["jobs"] == jobs["jobs"]
    stale = await client.put(f"{base}/jobs", json={"jobs": jobs["jobs"], "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"
    # another section is not made stale by a jobs save
    assert (await client.get(f"{base}/events")).json()["version"] == events_v
    ok = await client.put(
        f"{base}/events", json={"events": (await client.get(f"{base}/events")).json()["events"], "expected_version": events_v}
    )
    assert ok.status_code == 200, ok.text
    # null removes the block
    gone = await client.put(f"{base}/jobs", json={"jobs": None})
    assert gone.json()["jobs"] is None and gone.json()["version"] == 3
    assert (await client.get(f"/projects/{pid}/spec")).json()["jobs"] is None


async def test_unknown_keys_are_refused(client: AsyncClient) -> None:
    pid = await make_project(client)
    url = f"/projects/{pid}/behavior/jobs"
    assert (await client.put(url, json={"jobs": {"enabled": True, "bogus": 1}})).status_code == 422
    assert (await client.put(url, json={"extra": 1})).status_code == 422


async def test_issues_are_reported_per_section(client: AsyncClient) -> None:
    pid = await make_project(client)
    # webhooks without events/jobs/providers: saved as work in progress, problems listed
    fixture = _fixture("webhooks_orders")
    await client.put(
        f"/projects/{pid}/behavior/webhooks", json={"webhooks": fixture["webhooks"]}
    )
    issues = (await client.get(f"/projects/{pid}/behavior/issues")).json()["issues"]
    assert issues and all(i["path"].startswith("webhooks") for i in issues)


async def test_a_secret_is_never_stored(client: AsyncClient) -> None:
    pid = await make_project(client)
    fixture = _fixture("notifications_orders")
    notifications = json.loads(json.dumps(fixture["notifications"]))
    dump = json.dumps(notifications)
    assert "secret_in_spec" not in dump
    notifications["types"][0]["templates"][0]["body"] = "key sk_" "live_abcdefghijklmnop1234567890 {{ name }}"
    r = await client.put(f"/projects/{pid}/behavior/notifications", json={"notifications": notifications})
    assert r.status_code == 422 and r.json()["code"] == "secret_in_spec"
    assert (await client.get(f"/projects/{pid}/behavior/notifications")).json()["notifications"] is None


async def test_op_log_undo_redo_and_restore_return_the_blocks_exactly(client: AsyncClient) -> None:
    pid = await make_project(client)
    s0 = await _canon(client, pid)
    assert (await client.put(f"/projects/{pid}/spec", json=_fixture("combined_async"))).status_code == 200
    s1 = await _canon(client, pid)
    assert s1 != s0
    base = f"/projects/{pid}/behavior"
    jobs = (await client.get(f"{base}/jobs")).json()["jobs"]
    changed = {**jobs, "enabled": not jobs["enabled"]}
    assert (await client.put(f"{base}/jobs", json={"jobs": changed})).status_code == 200
    s2 = await _canon(client, pid)
    assert s2 != s1
    assert (await client.put(f"{base}/api-edge", json={"api_edge": None})).status_code == 200

    undo = await client.post(f"/projects/{pid}/spec/undo")
    assert undo.status_code == 200, undo.text
    assert await _canon(client, pid) == s2
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _canon(client, pid) == s1
    assert (await client.post(f"/projects/{pid}/spec/undo")).status_code == 200
    assert await _canon(client, pid) == s0  # blocks removed again
    assert (await client.get(f"{base}/events")).json()["events"] is None
    for expected in (s1, s2):
        assert (await client.post(f"/projects/{pid}/spec/redo")).status_code == 200
        assert await _canon(client, pid) == expected

    # restore to the state right after the first op (the whole fixture), then to the start
    r = await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": 1})
    assert r.status_code == 200, r.text
    assert await _canon(client, pid) == s1
    r = await client.post(f"/projects/{pid}/spec/restore", json={"to_seq": 0})
    assert r.status_code == 200, r.text
    assert await _canon(client, pid) == s0


async def test_viewer_reads_but_cannot_write(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    pid = await make_project(owner)
    await add_to_project_org(pid, "viewer@example.com")
    added = await owner.post(
        f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201
    await owner.put(f"/projects/{pid}/spec", json=_fixture("workflows_orders"))
    for key in BLOCKS:
        url = f"/projects/{pid}/behavior/{key.replace('_', '-')}"
        assert (await viewer.get(url)).status_code == 200
        assert (await viewer.put(url, json={})).status_code == 403
        assert (await stranger.get(url)).status_code == 404
    assert (await owner.put(f"/projects/{pid}/behavior/jobs", json={"jobs": None})).status_code == 200


async def test_generation_uses_the_stored_blocks(client: AsyncClient) -> None:
    pid = await make_project(client)
    await client.put(f"/projects/{pid}/spec", json=_fixture("combined_async"))
    paths = {f["path"] for f in (await client.post(f"/projects/{pid}/generate/preview")).json()["files"]}
    assert any(p.startswith("app/jobs") for p in paths), sorted(paths)[:40]
    await client.put(f"/projects/{pid}/behavior/jobs", json={"jobs": None})
    paths = {f["path"] for f in (await client.post(f"/projects/{pid}/generate/preview")).json()["files"]}
    assert not any(p.startswith("app/jobs") for p in paths)


SECRETS = {
    "sk": "sk_" "live_abcdefghijklmnop1234",
    "gh": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "slack": "xox" "b-1234567890-abcdefghij",
    "aws": "AKIA" "ABCDEFGHIJKLMNOP",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghij",
}


@pytest.mark.parametrize("kind", sorted(SECRETS))
async def test_secrets_are_refused_even_in_a_disabled_block(client: AsyncClient, kind: str) -> None:
    pid = await make_project(client)
    adapters = [{"kind": "email", "name": "smtpx", "settings": {"host": SECRETS[kind]}}]
    body = {"enabled": False, "adapters": adapters}
    r = await client.put(f"/projects/{pid}/behavior/providers", json={"providers": body})
    assert r.status_code == 422 and r.json()["code"] == "secret_in_spec", r.text
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    spec["providers"] = body
    whole = await client.put(f"/projects/{pid}/spec", json=spec)
    assert whole.status_code == 422
    assert SECRETS[kind] not in json.dumps((await client.get(f"/projects/{pid}/spec")).json())


async def test_secret_under_a_secret_key_name_and_in_a_disabled_notifications_block(
    client: AsyncClient,
) -> None:
    pid = await make_project(client)
    long_token = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA"
    adapters = [{"kind": "email", "name": "smtpx", "settings": {"password": long_token}}]
    r = await client.put(
        f"/projects/{pid}/behavior/providers", json={"providers": {"enabled": False, "adapters": adapters}}
    )
    assert r.status_code == 422
    nf = json.loads(json.dumps(_fixture("notifications_orders")["notifications"]))
    nf["enabled"] = False
    nf["types"][0]["templates"][0]["body"] = "ghp_" "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8 {{ name }}"
    r = await client.put(f"/projects/{pid}/behavior/notifications", json={"notifications": nf})
    assert r.status_code == 422 and r.json()["code"] == "secret_in_spec"


async def test_an_empty_body_does_not_delete_a_block(client: AsyncClient) -> None:
    pid = await make_project(client)
    await client.put(f"/projects/{pid}/spec", json=_fixture("combined_async"))
    url = f"/projects/{pid}/behavior/jobs"
    before = (await client.get(url)).json()
    r = await client.put(url, json={})
    assert r.status_code == 422 and r.json()["code"] == "missing_block"
    assert (await client.put(url, json={"expected_version": before["version"]})).status_code == 422
    assert (await client.get(url)).json() == before


async def test_concurrent_first_saves_conflict_instead_of_failing(client: AsyncClient) -> None:
    pid = await make_project(client)
    url = f"/projects/{pid}/behavior/jobs"
    results = await asyncio.gather(
        *[client.put(url, json={"jobs": {"enabled": False}, "expected_version": 0}) for _ in range(6)]
    )
    codes = sorted(r.status_code for r in results)
    assert 500 not in codes and codes.count(200) == 1 and set(codes) <= {200, 409}, codes


async def _editor(client_for: ClientFor, owner: AsyncClient) -> tuple[AsyncClient, str]:
    editor = await client_for("editor@example.com")
    pid = await make_project(owner)
    await add_to_project_org(pid, "editor@example.com")
    added = await owner.post(
        f"/projects/{pid}/members", json={"email": "editor@example.com", "role": "editor"}
    )
    assert added.status_code == 201
    return editor, pid


async def test_only_an_owner_changes_effectful_hooks(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    editor, pid = await _editor(client_for, owner)
    fixture = _fixture("hooks_effects")
    spec_url = f"/projects/{pid}/spec"
    # the editor cannot switch effects on, by the section route or by the whole spec
    assert (
        await editor.put(
            f"/projects/{pid}/behavior/hook-effects",
            json={"hook_effects": fixture["hook_effects"]},
        )
    ).status_code == 403
    denied = await editor.put(spec_url, json=fixture)
    assert denied.status_code == 403, denied.text
    assert (await owner.get(spec_url)).json()["hook_effects"] is None
    # the owner can
    assert (await owner.put(spec_url, json=fixture)).status_code == 200
    # the editor may keep editing everything else, with the same effects block and hooks
    same = (await editor.get(spec_url)).json()
    same["project"]["description"] = "edited by an editor"
    assert (await editor.put(spec_url, json=same)).status_code == 200
    # but not change them: strip hook effects through the hooks route, whole spec, or undo
    hooks = (await editor.get(f"/projects/{pid}/behavior/hooks")).json()["hooks"]
    for h in hooks:
        h["effects"] = []
    assert (await editor.put(f"/projects/{pid}/behavior/hooks", json={"hooks": hooks})).status_code == 403
    off = (await editor.get(spec_url)).json()
    off["hook_effects"]["webhook_hosts"] = ["hooks.example.com"]
    assert (await editor.put(spec_url, json=off)).status_code == 403
    # undoing the owner's change is the owner's too
    r = await editor.post(f"/projects/{pid}/spec/undo")
    assert r.status_code == 403, r.text
    assert (await owner.get(spec_url)).json()["hook_effects"] is not None
