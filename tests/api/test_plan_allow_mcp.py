"""Review F-013: `plans.allow_mcp` is enforced (token creation and MCP use), whatever the cap."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.exceptions import AppError
from app.models.enums import MemberRole
from app.models.platform import AuditLog, Plan, ProjectMember
from app.services.mcp_service import McpService
from tests.api.conftest import ClientFor
from tests.api.test_mcp import _principal
from tests.api.test_sso_config import set_plan

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def mcp_off_on_business(session_factory: Factory) -> AsyncGenerator[None, None]:
    """`business` with MCP switched off but a generous cap, so only the flag can refuse."""
    async with session_factory() as s:
        plan = await s.get(Plan, "business")
        assert plan is not None
        before = (plan.allow_mcp, plan.max_mcp_tokens)
        plan.allow_mcp, plan.max_mcp_tokens = False, 50
        await s.commit()
    yield
    async with session_factory() as s:
        plan = await s.get(Plan, "business")
        assert plan is not None
        plan.allow_mcp, plan.max_mcp_tokens = before
        await s.commit()


async def _business_org(client_for: ClientFor, session_factory: Factory):  # noqa: ANN202
    owner = await client_for("mcp-owner@example.com")
    org = (await owner.post("/orgs", json={"name": "M", "slug": "mcp-co"})).json()
    await set_plan(session_factory, org["id"], "business")
    r = await owner.put("/account/me/default-organization", json={"organization_id": org["id"]})
    assert r.status_code == 200, r.text
    return owner, org


@pytest.mark.usefixtures("mcp_off_on_business")
async def test_mcp_token_refused_when_the_plan_has_no_mcp(
    client_for: ClientFor, session_factory: Factory
) -> None:
    owner, org = await _business_org(client_for, session_factory)
    r = await owner.post("/account/tokens", json={"name": "m", "scopes": ["mcp:read"]})
    assert r.status_code == 402 and r.json()["code"] == "mcp_not_in_plan", r.text
    detail = r.json()["details"][0]
    assert detail["reason"] == "feature" and detail["organization_slug"] == "mcp-co"
    plain = await owner.post("/account/tokens", json={"name": "p", "scopes": ["read"]})
    assert plain.status_code == 201, plain.text
    async with session_factory() as s:
        denied = [
            a
            for a in (await s.execute(AuditLog.__table__.select())).all()
            if a.action == "quota.denied"
        ]
    assert any(a.detail["resource"] == "mcp_tokens" for a in denied)


async def test_mcp_token_allowed_when_the_plan_has_mcp(
    client_for: ClientFor, session_factory: Factory
) -> None:
    owner, _ = await _business_org(client_for, session_factory)
    r = await owner.post("/account/tokens", json={"name": "m", "scopes": ["mcp:read"]})
    assert r.status_code == 201, r.text


async def test_existing_mcp_use_stops_after_a_downgrade(
    client_for: ClientFor, session_factory: Factory
) -> None:
    owner, org = await _business_org(client_for, session_factory)
    made = await owner.post("/projects", json={"name": "P", "organization_id": org["id"]})
    assert made.status_code == 201, made.text
    project_id = uuid.UUID(made.json()["id"])
    async with session_factory() as s:
        member = await s.get(ProjectMember, (project_id, owner.user.id))  # type: ignore[attr-defined]
        assert member is not None
        member.mcp_enabled, member.role = True, MemberRole.owner
        await s.commit()
    principal = await _principal(owner.user)  # type: ignore[attr-defined]
    async with session_factory() as db:
        await McpService(db).get_project_spec(principal, project_id)  # works on business
    await set_plan(session_factory, org["id"], "free")
    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await McpService(db).get_project_spec(principal, project_id)
    assert exc.value.status_code == 402 and exc.value.code == "mcp_not_in_plan"
