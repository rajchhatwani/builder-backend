"""B3-5 API + service: approvals A-E, bound to spec hash and commit, expiring, owner-gated."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun
from app.models.platform import AuditLog
from app.services.agent.approval_service import ApprovalService
from app.services.agent.contract import ApprovalKind, ApprovalRequest
from tests.api._approval_hash import reviewer_sends_hash  # noqa: F401  (isort: skip)
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

H1, H2 = "a" * 64, "b" * 64
C1, C2 = "1" * 40, "2" * 40


async def _run(sf: async_sessionmaker[AsyncSession], pid: str) -> uuid.UUID:
    async with sf() as s:
        run = AiRun(project_id=uuid.UUID(pid), goal="add a field")
        s.add(run)
        await s.commit()
        return run.id


async def _ask(
    sf: async_sessionmaker[AsyncSession],
    pid: str,
    run_id: uuid.UUID,
    kind: str = "B",
    payload: dict[str, Any] | None = None,
    spec_hash: str = H1,
    commit: str | None = C1,
    settings: Any = None,
) -> uuid.UUID:
    async with sf() as s:
        run = await s.get(AiRun, run_id)
        assert run is not None
        row = await ApprovalService(s, settings or Settings()).request(
            run,
            ApprovalRequest(ApprovalKind(kind), "do the thing", payload or {"summary": "x"}),
            spec_hash=spec_hash,
            commit=commit,
        )
        await s.commit()
        return row.id


async def _valid(
    sf: async_sessionmaker[AsyncSession], run_id: uuid.UUID, kind: str = "B", h: str = H1, c: str | None = C1
) -> str:
    """'ok' or the AppError code."""
    async with sf() as s:
        try:
            await ApprovalService(s, Settings()).require_valid(run_id, kind, spec_hash=h, commit=c)
        except AppError as exc:
            assert exc.status_code == 409
            return exc.code
        return "ok"


def _url(pid: str, aid: object = None, tail: str = "") -> str:
    base = f"/projects/{pid}/agent/approvals"
    return f"{base}/{aid}{tail}" if aid else base


async def _team(client: AsyncClient, client_for: ClientFor, pid: str) -> tuple[AsyncClient, AsyncClient]:
    for mail in ("ed@example.com", "vi@example.com"):
        await add_to_project_org(pid, mail)
    ed = await client_for("ed@example.com")
    vi = await client_for("vi@example.com")
    for mail in ("ed@example.com", "vi@example.com"):
        await add_to_project_org(pid, mail)
    r = await client.post(f"/projects/{pid}/members", json={"email": "ed@example.com", "role": "editor"})
    assert r.status_code == 201
    r = await client.post(f"/projects/{pid}/members", json={"email": "vi@example.com", "role": "viewer"})
    assert r.status_code == 201
    return ed, vi


YES = {"approve": True, "note": "ok"}


async def test_flow_inbox_decide_audit_and_valid(
    client: AsyncClient, client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    ed, vi = await _team(client, client_for, pid)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    assert await _valid(session_factory, run) == "approval_missing"  # asked, not yet answered
    inbox = (await vi.get(_url(pid) + "?state=pending")).json()
    assert [a["id"] for a in inbox] == [str(aid)] and inbox[0]["state"] == "pending"
    assert inbox[0]["requires_owner"] is False and inbox[0]["bound_spec_hash"] == H1
    assert (await vi.get(_url(pid, aid))).status_code == 200
    r = await ed.post(_url(pid, aid, "/decision"), json=YES)
    assert r.status_code == 200 and r.json()["state"] == "approved" and r.json()["decided_by"]
    assert (await vi.get(_url(pid) + "?state=pending")).json() == []
    assert await _valid(session_factory, run) == "ok"
    async with session_factory() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == "agent.approval.approve")
            )
        ).scalar_one()
        assert n == 1


async def test_stale_spec_or_commit_is_never_accepted(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    assert (await client.post(_url(pid, aid, "/decision"), json=YES)).status_code == 200
    assert await _valid(session_factory, run) == "ok"
    assert await _valid(session_factory, run, h=H2) == "approval_stale"  # spec changed after approval
    assert await _valid(session_factory, run, c=C2) == "approval_stale"  # commit changed
    assert await _valid(session_factory, run, c=None) == "approval_stale"
    assert await _valid(session_factory, run, h=H2, c=C2) == "approval_stale"
    assert await _valid(session_factory, run, kind="C") == "approval_missing"  # other kind
    other = await _run(session_factory, pid)
    assert await _valid(session_factory, other) == "approval_missing"  # other run


async def test_approval_bound_without_commit_rejects_a_commit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run, commit=None)
    await client.post(_url(pid, aid, "/decision"), json=YES)
    assert await _valid(session_factory, run, c=None) == "ok"
    assert await _valid(session_factory, run, c=C1) == "approval_stale"


async def test_expired_cannot_be_decided_and_is_not_valid(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    past = datetime.now(UTC) - timedelta(seconds=1)
    async with session_factory() as s:
        await s.execute(update(AiApproval).where(AiApproval.id == aid).values(expires_at=past))
        await s.commit()
    assert (await client.get(_url(pid) + "?state=pending")).json() == []
    assert (await client.get(_url(pid, aid))).json()["state"] == "expired"
    r = await client.post(_url(pid, aid, "/decision"), json=YES)
    assert r.status_code == 409 and r.json()["code"] == "approval_expired"
    async with session_factory() as s:
        assert (await s.get(AiApproval, aid)).state == "expired"  # type: ignore[union-attr]
    assert await _valid(session_factory, run) == "approval_expired"
    assert [a["id"] for a in (await client.get(_url(pid) + "?state=expired")).json()] == [str(aid)]


async def test_approved_then_expired_is_not_valid(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    await client.post(_url(pid, aid, "/decision"), json=YES)
    async with session_factory() as s:
        await s.execute(
            update(AiApproval).where(AiApproval.id == aid).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert await _valid(session_factory, run) == "approval_expired"


async def test_double_decide_and_race(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    assert (await client.post(_url(pid, aid, "/decision"), json=YES)).status_code == 200
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": False})
    assert r.status_code == 409 and r.json()["code"] == "approval_already_decided"
    assert (await client.get(_url(pid, aid))).json()["state"] == "approved"  # the denial did not win

    aid2 = await _ask(session_factory, pid, run, kind="C")
    from app.models.platform import ProjectMember

    async with session_factory() as s0:
        users = list(
            (
                await s0.execute(
                    select(ProjectMember.user_id).where(ProjectMember.project_id == uuid.UUID(pid))
                )
            ).scalars()
        )
    assert users

    seen_hash = (await client.get(_url(pid, aid2))).json()["payload_hash"]

    async def go(approve: bool) -> str:
        async with session_factory() as s:
            try:
                await ApprovalService(s, Settings()).decide(
                    uuid.UUID(pid), aid2, users[0], approve, None, expected_payload_hash=seen_hash
                )
                await s.commit()
                return "ok"
            except AppError as exc:
                return exc.code

    results = await asyncio.gather(go(True), go(False), go(True))
    assert sorted(results) == ["approval_already_decided", "approval_already_decided", "ok"]


async def test_roles_editor_cannot_decide_d_e_or_hook_payloads(
    client: AsyncClient, client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    ed, vi = await _team(client, client_for, pid)
    run = await _run(session_factory, pid)
    d = await _ask(session_factory, pid, run, kind="D", payload={"drops": "Item.note"})
    e = await _ask(session_factory, pid, run, kind="E")
    hk = await _ask(session_factory, pid, run, kind="C", payload={"hook": "match_invoice"})
    fx = await _ask(session_factory, pid, run, kind="B", payload={"ops": [{"set": {"effects": ["email"]}}]})
    for aid in (d, e, hk, fx):
        r = await ed.post(_url(pid, aid, "/decision"), json=YES)
        assert r.status_code == 403, (aid, r.text)
        assert (await vi.post(_url(pid, aid, "/decision"), json=YES)).status_code == 403
    async with session_factory() as s:
        rows = (await s.execute(select(AiApproval.state).where(AiApproval.run_id == run))).scalars().all()
        assert set(rows) == {"pending"}
    shown = (await ed.get(_url(pid, d))).json()
    assert shown["requires_owner"] is True
    for aid in (d, e, hk, fx):
        assert (await client.post(_url(pid, aid, "/decision"), json=YES)).status_code == 200


async def test_viewer_cannot_decide_any_kind_but_can_read(
    client: AsyncClient, client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    _ed, vi = await _team(client, client_for, pid)
    run = await _run(session_factory, pid)
    for kind in "ABCDE":
        aid = await _ask(session_factory, pid, run, kind=kind)
        assert (await vi.post(_url(pid, aid, "/decision"), json=YES)).status_code == 403
        assert (await vi.get(_url(pid, aid))).status_code == 200
    assert len((await vi.get(_url(pid) + "?state=pending")).json()) == 5
    # a non-member does not even learn the project exists
    eve = await client_for("eve@example.com")
    assert (await eve.get(_url(pid))).status_code == 404


async def test_cross_project_id_is_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    other = await make_project(client, "Other")
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    assert (await client.get(_url(other, aid))).status_code == 404
    assert (await client.post(_url(other, aid, "/decision"), json=YES)).status_code == 404
    assert (await client.get(_url(other))).json() == []
    assert (await client.get(_url(pid, aid))).json()["state"] == "pending"
    assert (await client.get(_url(pid, uuid.uuid4()))).status_code == 404


async def test_deny_then_require_valid(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run)
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": False, "note": "no"})
    assert r.status_code == 200 and r.json()["state"] == "denied" and r.json()["decision_note"] == "no"
    assert await _valid(session_factory, run) == "approval_denied"
    # asking again is a new question, and it must be answered afresh
    again = await _ask(session_factory, pid, run)
    assert await _valid(session_factory, run) == "approval_missing"
    await client.post(_url(pid, again, "/decision"), json=YES)
    assert await _valid(session_factory, run) == "ok"


async def test_supersede_older_pending_of_same_kind_only(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    first = await _ask(session_factory, pid, run, spec_hash=H1)
    other_kind = await _ask(session_factory, pid, run, kind="C")
    second = await _ask(session_factory, pid, run, spec_hash=H2)
    assert (await client.get(_url(pid, first))).json()["state"] == "superseded"
    assert (await client.get(_url(pid, other_kind))).json()["state"] == "pending"
    assert (await client.get(_url(pid, second))).json()["state"] == "pending"
    r = await client.post(_url(pid, first, "/decision"), json=YES)
    assert r.status_code == 409
    await client.post(_url(pid, second, "/decision"), json=YES)
    assert await _valid(session_factory, run, h=H2) == "ok"
    assert await _valid(session_factory, run, h=H1) == "approval_stale"
    # an approved one is never superseded by a later request
    third = await _ask(session_factory, pid, run, spec_hash=H1)
    assert (await client.get(_url(pid, second))).json()["state"] == "approved"
    assert (await client.get(_url(pid, third))).json()["state"] == "pending"


async def test_bad_filter_and_validation(client: AsyncClient) -> None:
    pid = await make_project(client)
    assert (await client.get(_url(pid) + "?state=bogus")).status_code == 422
    assert (await client.get(_url(pid) + "?limit=0")).status_code == 422
    assert (await client.post(_url(pid, uuid.uuid4(), "/decision"), json={})).status_code == 422
    assert (await client.post(_url(pid, uuid.uuid4(), "/decision"), json={"approve": True, "note": "x" * 501})).status_code == 422


async def test_risk_flags_and_dependency_flag_are_stored(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run, payload={"dependencies": ["left-pad"]})
    assert (await client.get(_url(pid, aid))).json()["risk_flags"] == ["new_dependencies"]


async def test_org_policy_auto_approves_only_small_plan_edits(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    relax = SimpleNamespace(
        ai_approval_auto_plan_small_edit=True,
        ai_approval_roles={"D": "editor"},
    )
    small = await _ask(session_factory, pid, run, "A", {"small_config_edit": True}, settings=relax)
    assert (await client.get(_url(pid, small))).json()["state"] == "approved"
    assert await _valid(session_factory, run, "A") == "ok"
    big = await _ask(session_factory, pid, run, "A", {"summary": "new entity"}, settings=relax)
    assert (await client.get(_url(pid, big))).json()["state"] == "pending"
    for kind in "BCDE":  # the same flag never approves B-E
        aid = await _ask(session_factory, pid, run, kind, {"small_config_edit": True}, settings=relax)
        assert (await client.get(_url(pid, aid))).json()["state"] == "pending"
    hooky = await _ask(session_factory, pid, run, "A", {"small_config_edit": True, "hook": "h"}, settings=relax)
    assert (await client.get(_url(pid, hooky))).json()["state"] == "pending"


async def test_gate_a_approve_with_edited_plan(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    original = {"entities": ["Invoice", "Customer"], "hooks": ["h1"]}
    aid = await _ask(session_factory, pid, run, "A", {"plan": original})
    edited = {"entities": ["Invoice"], "junk": ["x"], "hooks": []}
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": True, "plan": edited})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "approved"
    assert body["payload"]["plan"] == {"entities": ["Invoice"]}  # cleaned: unknown keys and empties dropped
    assert body["payload"]["edited_from"] == original and body["payload"]["edited_by"]


async def test_edited_plan_only_on_approved_gate_a_and_never_empty(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    run = await _run(session_factory, pid)
    plan = {"entities": ["Invoice"]}
    a = await _ask(session_factory, pid, run, "A", {"plan": plan})
    r = await client.post(_url(pid, a, "/decision"), json={"approve": False, "plan": plan})
    assert r.status_code == 422 and r.json()["code"] == "plan_edit_not_allowed"
    r = await client.post(_url(pid, a, "/decision"), json={"approve": True, "plan": {"junk": ["x"]}})
    assert r.status_code == 422 and r.json()["code"] == "plan_empty"
    b = await _ask(session_factory, pid, run, "B")
    r = await client.post(_url(pid, b, "/decision"), json={"approve": True, "plan": plan})
    assert r.status_code == 422 and r.json()["code"] == "plan_edit_not_allowed"
    # none of the refusals decided anything
    assert (await client.get(_url(pid, a))).json()["state"] == "pending"
    assert (await client.post(_url(pid, a, "/decision"), json=YES)).status_code == 200


async def test_editor_cannot_widen_gate_a_with_hooks_or_dependencies(
    client: AsyncClient, client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """SENTINEL CP-E M1: the owner rule must see the EDITED plan, not the old payload."""
    pid = await make_project(client)
    ed, _vi = await _team(client, client_for, pid)
    run = await _run(session_factory, pid)
    aid = await _ask(session_factory, pid, run, "A", {"plan": {"entities": ["Invoice"]}})
    r = await ed.post(
        _url(pid, aid, "/decision"),
        json={"approve": True, "plan": {"entities": ["Invoice"], "hooks": ["steal"], "dependencies": ["evilpkg"]}},
    )
    assert r.status_code == 403, r.text
    assert (await client.get(_url(pid, aid))).json()["state"] == "pending"
    ok = await ed.post(_url(pid, aid, "/decision"), json={"approve": True, "plan": {"entities": ["Invoice", "Payroll"]}})
    assert ok.status_code == 200, ok.text  # a plain entity plan is still the editor's call
    owner = await _ask(session_factory, pid, run, "A", {"plan": {"entities": ["X"]}})
    assert (await client.post(_url(pid, owner, "/decision"), json={"approve": True, "plan": {"hooks": ["h"]}})).status_code == 200


async def test_plan_extension_for_hook_zone_or_dependency_is_owner_only(
    client: AsyncClient, client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """SENTINEL CP-E M2: `extend.kind` is a value, so the owner rule has to look at it explicitly."""
    pid = await make_project(client)
    ed, _vi = await _team(client, client_for, pid)
    run = await _run(session_factory, pid)
    for kind in ("hook", "zone", "dependency"):
        aid = await _ask(session_factory, pid, run, "A", {"extend": {"kind": kind, "name": "x"}})
        assert (await client.get(_url(pid, aid))).json()["requires_owner"] is True
        assert (await ed.post(_url(pid, aid, "/decision"), json=YES)).status_code == 403
    ent = await _ask(session_factory, pid, run, "A", {"extend": {"kind": "entity", "name": "Payroll"}})
    assert (await ed.post(_url(pid, ent, "/decision"), json=YES)).status_code == 200


# -- S3-004/S3-005: a decision is bound to what the reviewer saw ---------------------------------
async def _state(sf: async_sessionmaker[AsyncSession], aid: uuid.UUID) -> str:
    async with sf() as s:
        row = await s.get(AiApproval, aid)
        assert row is not None
        return row.state


async def test_approve_with_seen_hash_ok_and_read_model_serves_it(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    aid = await _ask(session_factory, pid, await _run(session_factory, pid))
    seen = (await client.get(_url(pid, aid))).json()
    assert len(seen["payload_hash"]) == 64
    body = {"approve": True, "expected_payload_hash": seen["payload_hash"], "expected_spec_hash": seen["bound_spec_hash"]}
    r = await client.post(_url(pid, aid, "/decision"), json=body)
    assert r.status_code == 200 and r.json()["state"] == "approved"


async def test_wrong_hash_is_409_and_stays_pending(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    aid = await _ask(session_factory, pid, await _run(session_factory, pid))
    seen = (await client.get(_url(pid, aid))).json()
    r = await client.post(
        _url(pid, aid, "/decision"),
        json={"approve": True, "expected_payload_hash": seen["payload_hash"], "expected_spec_hash": H2},
    )
    assert r.status_code == 409 and r.json()["code"] == "approval_changed"  # right payload, wrong spec
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": True, "expected_payload_hash": "0" * 64})
    assert r.status_code == 409 and "approval_changed" in r.text
    assert await _state(session_factory, aid) == "pending"


async def test_approve_without_hash_is_refused(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    aid = await _ask(session_factory, pid, await _run(session_factory, pid))
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": True}, headers={"x-raw-decision": "1"})
    assert r.status_code == 422 and "payload_hash_required" in r.text
    assert await _state(session_factory, aid) == "pending"


async def test_deny_without_hash_is_fine(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    aid = await _ask(session_factory, pid, await _run(session_factory, pid))
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": False})
    assert r.status_code == 200 and r.json()["state"] == "denied"


async def test_payload_mutated_after_reading_refuses_old_hash(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    aid = await _ask(session_factory, pid, await _run(session_factory, pid))
    old = (await client.get(_url(pid, aid))).json()["payload_hash"]
    async with session_factory() as s:  # the agent re-requests / someone widens the payload
        await s.execute(
            update(AiApproval).where(AiApproval.id == aid).values(payload={"summary": "wider"}, payload_hash="f" * 64)
        )
        await s.commit()
    r = await client.post(_url(pid, aid, "/decision"), json={"approve": True, "expected_payload_hash": old})
    assert r.status_code == 409 and "approval_changed" in r.text
    assert await _state(session_factory, aid) == "pending"
