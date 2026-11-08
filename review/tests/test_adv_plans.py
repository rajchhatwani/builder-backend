"""Adversarial review: plan flags and overrides actually enforced (REQ-§3.1 plans.allow_mcp, §6.2, §6.5, §7 Plans tab).
Run: uv run python -m pytest review/tests/test_adv_plans.py -p no:cacheprovider -q
"""
from sqlalchemy import text

from tests.api.conftest import _FACTORY, ClientFor


async def test_allow_mcp_false_is_enforced(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    u = await client_for("mcpflag@example.com")
    org = next(o for o in (await u.get("/orgs")).json()["items"] if o["kind"] == "personal")
    async with _FACTORY[0]() as s:
        await s.execute(text("update plans set allow_mcp=false, max_mcp_tokens=50 where id='business'"))
        await s.execute(text("update subscriptions set plan_id='business' where organization_id=:o"), {"o": org["id"]})
        await s.commit()
    try:
        r = await u.post("/account/tokens", json={"name": "mcp", "scopes": ["mcp:read"]})
        assert r.status_code == 402, f"allow_mcp=false but an MCP token was minted ({r.status_code}): plans.allow_mcp is never read"
    finally:
        async with _FACTORY[0]() as s:
            await s.execute(text("update plans set allow_mcp=true, max_mcp_tokens=25 where id='business'"))
            await s.commit()


async def test_seat_override_lower_than_usage_and_zero(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """seat_override = 0 is falsy in the plan's pseudo-code (`seat_override or max_seats`); the code uses `is not None`."""
    owner = await client_for("ovr@example.com")
    org = (await owner.post("/orgs", json={"name": "O", "slug": "ovr-co"})).json()
    async with _FACTORY[0]() as s:
        await s.execute(text("update subscriptions set plan_id='team', seat_override=0 where organization_id=:o"), {"o": org["id"]})
        await s.commit()
    r = await owner.post("/orgs/ovr-co/invitations", json={"email": "a@example.com", "role": "member"})
    assert r.status_code == 402, r.status_code  # override 0 means no seats beyond... (documenting behaviour)


async def test_locked_and_deleting_org_blocks_writes_everywhere(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    owner = await client_for("lock@example.com")
    org = (await owner.post("/orgs", json={"name": "L", "slug": "lock-co"})).json()
    async with _FACTORY[0]() as s:
        await s.execute(text("update subscriptions set plan_id='team' where organization_id=:o"), {"o": org["id"]})
        await s.commit()
    pr = await owner.post("/projects", json={"name": "p", "slug": "p", "organization_id": org["id"]})
    assert pr.status_code == 201
    assert (await owner.delete("/orgs/lock-co")).status_code == 202
    probes = [
        ("POST", "/projects", {"name": "p2", "slug": "p2", "organization_id": org["id"]}),
        ("GET", f"/projects/{pr.json()['id']}", None),
        ("PUT", f"/projects/{pr.json()['id']}/spec", {}),
        ("POST", f"/projects/{pr.json()['id']}/generate/preview", {}),
        ("POST", "/orgs/lock-co/invitations", {"email": "z@example.com", "role": "member"}),
        ("POST", "/account/tokens", {"name": "x", "scopes": ["read"], "project_id": pr.json()["id"]}),
    ]
    out = {(m, p): (await owner.request(m, p, json=b)).status_code for m, p, b in probes}
    print("LOCKED-ORG PROBES:", {f"{k[0]} {k[1][:40]}": v for k, v in out.items()})
    assert all(v in (423, 404, 405, 422) for v in out.values()), out
