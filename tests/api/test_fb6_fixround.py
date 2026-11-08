"""FB6 fix round: D-1 multipart NUL guard scope, D-5 sweeper actor, ND-2 hook rename, ND-4 decide
authorization order, N1 promotion base check, N2 fetch guard, N4 abandoned awaiting_approval runs."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.config import Settings, get_settings
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun
from app.models.behavior_config import ProjectBehavior
from app.services.agent import approved_effects, sweeper
from app.services.agent.run_service import RunDriver
from app.services.agent.sweeper import sweep_once
from app.services.behavior_service import ACTOR_ROLE
from tests.api._approval_hash import reviewer_sends_hash  # noqa: F401  (isort: skip)
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor
from tests.api.test_agent_approvals import YES, _ask, _run, _team, _url
from tests.api.test_agent_e2e import _cleanup, _setup, ws_settings  # noqa: F401  (fixtures)
from tests.api.test_agent_runs import Factory, _patch_run, _run as _run_row
from tests.api.test_agent_fb2a import PAST, _crashed_run, _deps
from tests.api.test_agent_runs import FakeToolbox, ScriptedProvider, finish
from tests.api.test_behavior_hooks import _editor, _seed_hook, example

def _fx_hook() -> Any:
    from app.core.spec_models import SpecHook

    return SpecHook.model_validate({**example()["hooks"][0], "name": "h", "kind": "effect", "point": "Invoice.after_commit", "effects": ["email"]})


# -- D-5 ------------------------------------------------------------------------------------------


async def test_swept_recovery_runs_as_the_system_actor_and_only_there(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await make_project(client)
    rid = await _crashed_run(client, session_factory, pid, "applying", PAST)
    seen: list[str | None] = []
    before = ACTOR_ROLE.get()  # the test client shares our context, so it may hold a request role

    async def recover(self: RunDriver, run_id: uuid.UUID, max_recoveries: int) -> None:
        seen.append(ACTOR_ROLE.get())
        # the S2-016 rule: an effect-hook change is applied (system) ...
        from app.models.behavior_config import ProjectBehavior as PB
        from app.services.behavior_service import apply_section

        row = PB(project_id=uuid.UUID(pid), version=1, sections={})
        apply_section(row, "hooks", [_fx_hook()])

    monkeypatch.setattr(RunDriver, "recover", recover)
    provider = ScriptedProvider(lambda n, r: finish(n))
    taken = await sweep_once(session_factory, _deps(session_factory, provider, FakeToolbox()), get_settings())
    assert taken == [uuid.UUID(rid)] and seen == ["system"]
    assert ACTOR_ROLE.get() == before  # ... and the role does not leak out of the sweep
    from app.models.behavior_config import ProjectBehavior as PB
    from app.services.behavior_service import apply_section

    token = ACTOR_ROLE.set(None)
    with pytest.raises(AppError) as exc:  # the same change with no actor and no sweep stays denied
        apply_section(PB(project_id=uuid.UUID(pid), version=1, sections={}), "hooks", [_fx_hook()])
    ACTOR_ROLE.reset(token)
    assert exc.value.status_code == 403


# -- N4 -------------------------------------------------------------------------------------------


async def test_sweeper_stops_runs_whose_approvals_all_expired(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid = await make_project(client)
    expired = await _crashed_run(client, session_factory, pid, "awaiting_approval", PAST)
    waiting = await _crashed_run(client, session_factory, pid, "awaiting_approval", PAST)
    for rid, delta in ((expired, timedelta(hours=-1)), (waiting, timedelta(hours=1))):
        aid = await _ask(session_factory, pid, uuid.UUID(rid))
        async with session_factory() as s:
            await s.execute(update(AiApproval).where(AiApproval.id == aid).values(expires_at=datetime.now(UTC) + delta))
            await s.commit()
    provider = ScriptedProvider(lambda n, r: finish(n))
    await sweep_once(session_factory, _deps(session_factory, provider, FakeToolbox()), get_settings())
    gone = await _run_row(session_factory, expired)
    assert gone.state == "stopped" and gone.stop_code == "approval_expired" and gone.finished_at is not None
    assert (await _run_row(session_factory, waiting)).state == "awaiting_approval"  # still decidable


# -- ND-4 -----------------------------------------------------------------------------------------


async def test_non_deciders_get_403_before_any_hash_hint(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    pid = await make_project(client)
    ed, vi = await _team(client, client_for, pid)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run, kind="D", payload={"drops": "Item.note"})  # owner-only kind
    h = {"x-raw-decision": "1"}
    for who in (ed, vi):
        assert (await who.post(_url(pid, aid, "/decision"), json=YES, headers=h)).status_code == 403  # no hash
        bad = {**YES, "expected_payload_hash": "f" * 64}
        assert (await who.post(_url(pid, aid, "/decision"), json=bad, headers=h)).status_code == 403  # wrong hash
    assert (await client.post(_url(pid, aid, "/decision"), json=YES, headers=h)).status_code == 422  # owner is told


# -- ND-2 -----------------------------------------------------------------------------------------


async def test_renaming_an_ai_hook_keeps_it_ai(client: AsyncClient, client_for: ClientFor, session_factory: Factory) -> None:
    pid = await make_project(client)
    hook = {**example()["hooks"][0], "name": "ai_check", "author": "ai"}  # a pure AI hook, no effects
    async with session_factory() as s:
        s.add(ProjectBehavior(project_id=pid, version=1, sections={"hooks": [hook]}))
        await s.commit()
    ed = await _editor(client, client_for, pid)
    body = {k: v for k, v in hook.items() if k != "author"}
    res = await ed.put(f"/projects/{pid}/behavior/hooks", json={"hooks": [{**body, "name": "renamed"}]})
    assert res.status_code == 200, res.text
    assert [(h["name"], h["author"]) for h in res.json()["hooks"]] == [("renamed", "ai")]


async def test_a_legit_new_hook_stays_trusted_and_a_kept_ai_hook_stays_ai(
    client: AsyncClient, session_factory: Factory
) -> None:
    pid = await make_project(client)
    hook = await _seed_hook(session_factory, pid)
    fresh = {**example()["hooks"][0], "name": "brand_new"}
    res = await client.put(f"/projects/{pid}/behavior/hooks", json={"hooks": [hook, fresh]})
    by = {h["name"]: h["author"] for h in res.json()["hooks"]}
    assert by == {"mail_it": "ai", "brand_new": "trusted"}
    # removing the ai hook and adding an unrelated-point hook is a legit edit
    other = {**example()["hooks"][0], "name": "other", "point": "Invoice.validate"}
    res = await client.put(f"/projects/{pid}/behavior/hooks", json={"hooks": [other]})
    assert res.status_code == 200 and res.json()["hooks"][0]["author"] == "trusted", res.text


# -- N2 -------------------------------------------------------------------------------------------


def test_fetch_guard_invalid_port_is_a_typed_refusal() -> None:
    with pytest.raises(AppError) as exc:
        approved_effects.check_fetch_url("https://example.com:99999/")
    assert exc.value.code == "fetch_refused"


@pytest.mark.parametrize("ip", ["64:ff9b::7f00:1", "64:ff9b::a00:5", "::ffff:127.0.0.1", "2002:7f00:1::1", "64:ff9b:1::1"])
def test_embedded_ipv4_in_ipv6_is_judged_by_the_ipv4(ip: str) -> None:
    assert approved_effects._public_ip(ip) is False


def test_public_addresses_still_pass() -> None:
    assert approved_effects._public_ip("93.184.216.34") and approved_effects._public_ip("64:ff9b::5db8:d822")


async def test_fetch_has_one_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(url: str) -> dict[str, Any]:
        await asyncio.sleep(5)
        return {}

    monkeypatch.setattr(approved_effects, "_fetch_url", slow)
    monkeypatch.setattr(approved_effects, "FETCH_TOTAL_TIMEOUT", 0.05)
    with pytest.raises(AppError) as exc:
        await approved_effects.fetch_url("https://example.com/")
    assert exc.value.code == "fetch_failed"


# -- N1 -------------------------------------------------------------------------------------------


async def test_promotion_refuses_a_file_that_changed_on_main_since_the_draft_started(
    client: AsyncClient, ws_settings: Settings, session_factory: Factory  # noqa: F811
) -> None:
    from app.services.workspace_service import WorkspaceService

    pid = await make_project(client)
    branches = []
    for name in ("a", "b"):
        r = await client.post(f"/projects/{pid}/workspaces", json={"name": name})
        assert r.status_code == 201, r.text
        branches.append((r.json()["id"], r.json()["branch"]))
    try:
        rel = "app/custom/hooks/x.py"
        async with session_factory() as s:
            sha = await WorkspaceService(s, ws_settings).promote_files(uuid.UUID(pid), {rel: b"a = 1\n"}, "A", base_branch=branches[0][1])
        assert sha
        async with session_factory() as s:  # B started from the same old main, never saw A's file
            with pytest.raises(AppError) as exc:
                await WorkspaceService(s, ws_settings).promote_files(uuid.UUID(pid), {rel: b"b = 2\n"}, "B", base_branch=branches[1][1])
        assert exc.value.code == "base_changed"
        repo = Path(ws_settings.workspace_root or "") / pid / "repo"
        assert (repo / rel).read_text() == "a = 1\n"  # A's file was not overwritten
        async with session_factory() as s:  # identical bytes are idempotent, not a conflict
            assert await WorkspaceService(s, ws_settings).promote_files(uuid.UUID(pid), {rel: b"a = 1\n"}, "B2", base_branch=branches[1][1]) is None
        async with session_factory() as s:  # a file main never had is fine
            assert await WorkspaceService(s, ws_settings).promote_files(uuid.UUID(pid), {"app/custom/hooks/y.py": b"y = 1\n"}, "B3", base_branch=branches[1][1])
    finally:
        for wid, _ in branches:
            await client.delete(f"/projects/{pid}/workspaces/{wid}")
