"""MCP server + per-member access + project/admin token management.

The MCP tools run under a Streamable-HTTP transport; the HTTP layer is thin and all
business logic lives in `McpService` with a `Principal` for identity. Rather than
spinning up a real MCP client, these tests exercise the service directly against the
test Postgres and cover the REST endpoints that back the feature:

  * `PATCH /projects/{id}/members/{user_id}/mcp`  (owner-only toggle)
  * `GET /projects/{id}/tokens`                   (owner lists pinned tokens)
  * `DELETE /projects/{id}/tokens/{token_id}`     (owner revokes pinned tokens)
  * `GET /admin/users/{user_id}/tokens`           (admin lists all)
  * `DELETE /admin/users/{user_id}/tokens/{t}`    (admin revokes any)
  * `GET /admin/audit?via=mcp`                    (audit filter)
  * `GET /.well-known/oauth-protected-resource`   (discovery)

Access control invariants exercised against `McpService`:
  * membership + `mcp_enabled` required for every tool;
  * write tools additionally require editor-or-owner role;
  * pinned tokens cannot see other projects even when their owner is a member;
  * output is capped and control characters stripped;
  * every tool call writes an audit entry with `action="mcp.tool_call"`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import mcp as mcp_api
from app.core import platform_authz as authz
from app.exceptions import AppError
from app.models.enums import FieldType, MemberRole, PlatformRole, TokenAudience
from app.models.platform import ApiToken, AuditLog, PlatformUser, ProjectMember
from app.services.access_service import Principal
from app.services.mcp_service import MAX_RESPONSE_CHARS, McpService
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, MakeUser

ADMIN = PlatformRole.platform_admin


# ── helpers ──────────────────────────────────────────────────────────────────────────────


async def _principal(
    user: PlatformUser,
    *,
    scopes: tuple[str, ...] = (authz.SCOPE_MCP_READ,),
    pinned: uuid.UUID | None = None,
) -> Principal:
    return Principal(
        user=user,
        via="api_token",
        audience=TokenAudience.app,
        scopes=frozenset(scopes),
        token_project_id=pinned,
    )


async def _enable_mcp(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role: MemberRole = MemberRole.editor,
) -> None:
    """Add the user as a member of the project with mcp_enabled=True and the given role.

    If the user is already a member (e.g. the project owner), flip the flag instead.
    """
    async with session_factory() as session:
        existing = await session.get(ProjectMember, (project_id, user_id))
        if existing is None:
            session.add(
                ProjectMember(
                    project_id=project_id,
                    user_id=user_id,
                    role=role,
                    mcp_enabled=True,
                )
            )
        else:
            existing.mcp_enabled = True
        await session.commit()


async def _set_owner_mcp(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    enabled: bool,
) -> None:
    async with session_factory() as session:
        member = await session.get(ProjectMember, (project_id, user_id))
        assert member is not None
        member.mcp_enabled = enabled
        await session.commit()


# ── /.well-known/oauth-protected-resource ───────────────────────────────────────────────


async def test_oauth_protected_resource_metadata(anon_client: AsyncClient) -> None:
    r = await anon_client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    for name in (authz.SCOPE_MCP_READ, authz.SCOPE_MCP_WRITE, authz.SCOPE_MCP_GENERATE):
        assert name in body["scopes_supported"]
    assert body["mcp_endpoint"] == "/mcp"
    assert body["bearer_methods_supported"] == ["header"]


# ── membership + mcp_enabled gating (service layer) ─────────────────────────────────────


async def test_list_projects_returns_only_mcp_enabled_memberships(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    on = uuid.UUID(await make_project(client, "On"))
    # Also create an "off" project; mcp_enabled defaults to False, so it must not appear.
    await make_project(client, "Off")
    await _set_owner_mcp(session_factory, on, user.id, True)

    async with session_factory() as db:
        projects = await McpService(db).list_projects(await _principal(user))

    assert {p["id"] for p in projects} == {str(on)}
    assert projects[0]["your_role"] == "owner"


async def test_tool_denied_when_mcp_not_enabled(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    # Owner, but mcp_enabled defaults to False.

    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await McpService(db).get_project_spec(await _principal(user), project_id)
    assert exc.value.status_code == 403
    assert exc.value.code == "mcp_not_granted"


async def test_tool_denied_for_non_member_looks_like_missing(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, owner.id, True)
    stranger_client = await client_for("outsider@example.com")
    stranger: PlatformUser = stranger_client.user  # type: ignore[attr-defined]

    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await McpService(db).get_project_spec(await _principal(stranger), project_id)
    assert exc.value.status_code == 404
    assert exc.value.code == "not_found"


async def test_viewer_write_tool_denied_even_with_mcp_write_scope(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    viewer_client = await client_for("v@example.com")
    viewer: PlatformUser = viewer_client.user  # type: ignore[attr-defined]
    await _enable_mcp(session_factory, project_id, viewer.id, role=MemberRole.viewer)
    await _set_owner_mcp(session_factory, project_id, owner.id, True)

    scopes = (authz.SCOPE_MCP_READ, authz.SCOPE_MCP_WRITE)
    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await McpService(db).create_entity(
                await _principal(viewer, scopes=scopes), project_id, name="Item"
            )
    assert exc.value.status_code == 403
    assert exc.value.code == "forbidden"


async def test_editor_can_run_write_and_generate_tools(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    scopes = (
        authz.SCOPE_MCP_READ,
        authz.SCOPE_MCP_WRITE,
        authz.SCOPE_MCP_GENERATE,
    )
    async with session_factory() as db:
        p = await _principal(user, scopes=scopes)
        entity = await McpService(db).create_entity(p, project_id, name="Post")
        assert entity["name"] == "Post"
        field = await McpService(db).add_field(
            p,
            project_id,
            entity_name="Post",
            field={"name": "title", "type": "string"},
        )
        assert field["name"] == "title"
        gen = await McpService(db).generate_project(p, project_id)
        assert gen["download_url"].endswith("/generate/download")
        assert "generation_id" in gen


async def test_add_field_rejects_unknown_entity(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    scopes = (authz.SCOPE_MCP_READ, authz.SCOPE_MCP_WRITE)
    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await McpService(db).add_field(
                await _principal(user, scopes=scopes),
                project_id,
                entity_name="Ghost",
                field={"name": "x", "type": "string"},
            )
    assert exc.value.status_code == 404


# ── token pinning ───────────────────────────────────────────────────────────────────────


async def test_pinned_token_hides_other_projects(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    a = uuid.UUID(await make_project(client, "A"))
    b = uuid.UUID(await make_project(client, "B"))
    await _set_owner_mcp(session_factory, a, user.id, True)
    await _set_owner_mcp(session_factory, b, user.id, True)

    async with session_factory() as db:
        listed = await McpService(db).list_projects(
            await _principal(user, pinned=a)
        )
    assert {p["id"] for p in listed} == {str(a)}


async def test_pinned_token_still_sees_its_own_project(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        spec = await McpService(db).get_project_spec(
            await _principal(user, pinned=project_id), project_id
        )
    assert spec["project"]["name"] == "Shop"


# ── read tools return expected shapes ───────────────────────────────────────────────────


async def test_get_data_model_returns_entities_and_relations(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    entity_id = await make_entity(client, str(project_id), "Post")
    await client.post(
        f"/entities/{entity_id}/fields",
        json={"name": "title", "type": FieldType.string.value, "required": True},
    )
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        data = await McpService(db).get_data_model(await _principal(user), project_id)

    entities: list[dict[str, Any]] = data["entities"]  # type: ignore[assignment]
    assert len(entities) == 1
    assert entities[0]["name"] == "Post"
    field_names = {f["name"] for f in entities[0]["fields"]}
    assert "title" in field_names


async def test_get_auth_model_without_auth_block(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        auth = await McpService(db).get_auth_model(await _principal(user), project_id)
    assert auth == {"enabled": False}


async def test_get_frontend_contract_exposes_pagination_and_errors(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await make_entity(client, str(project_id), "Post")
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        contract = await McpService(db).get_frontend_contract(
            await _principal(user), project_id
        )

    assert contract["pagination"]["style"] == "limit_offset"  # type: ignore[index]
    assert set(contract["errors"]["common_codes"].keys()) >= {  # type: ignore[attr-defined,index]
        "401",
        "403",
        "404",
    }
    entities: list[dict[str, Any]] = contract["entities"]  # type: ignore[assignment]
    assert any(e["name"] == "Post" for e in entities)


async def test_get_deploy_info_without_deployment_block(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        info = await McpService(db).get_deploy_info(await _principal(user), project_id)
    assert info == {"enabled": False}


async def test_validate_spec_reports_issue_count(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        result = await McpService(db).validate_spec(await _principal(user), project_id)
    assert "valid" in result and "issue_count" in result
    assert isinstance(result["issues"], list)


# ── output safety ───────────────────────────────────────────────────────────────────────


async def test_output_is_capped_at_max_response_chars(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    # The description column is unbounded TEXT; the Pydantic PATCH schema caps user input
    # at 2000 chars, so write directly to the DB to prove the service-level cap.
    from app.models.project import Project as ProjectModel

    huge = "x" * (MAX_RESPONSE_CHARS + 500)
    async with session_factory() as session:
        project = await session.get(ProjectModel, project_id)
        assert project is not None
        project.description = huge
        await session.commit()

    async with session_factory() as db:
        spec = await McpService(db).get_project_spec(await _principal(user), project_id)
    assert len(spec["project"]["description"]) == MAX_RESPONSE_CHARS  # type: ignore[index]


async def test_control_characters_stripped_from_output(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    from app.models.project import Project as ProjectModel

    async with session_factory() as session:
        project = await session.get(ProjectModel, project_id)
        assert project is not None
        project.description = "safe\x1bevil\x07"
        await session.commit()

    async with session_factory() as db:
        spec = await McpService(db).get_project_spec(await _principal(user), project_id)
    desc: str = spec["project"]["description"]  # type: ignore[index,assignment]
    assert "\x1b" not in desc
    assert "\x07" not in desc


# ── audit trail ─────────────────────────────────────────────────────────────────────────


async def test_every_tool_call_writes_an_audit_entry(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, user.id, True)

    async with session_factory() as db:
        p = await _principal(user)
        await McpService(db).list_projects(p)
        await McpService(db).get_project_spec(p, project_id)
        await McpService(db).get_data_model(p, project_id)

    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "mcp.tool_call")
                )
            ).scalars()
        )
    tools = {(r.detail or {}).get("tool") for r in rows}
    assert {"list_projects", "get_project_spec", "get_data_model"} <= tools
    for r in rows:
        assert r.via == "api_token"
        assert (r.detail or {}).get("result") == "ok"


async def test_admin_audit_filter_by_via(
    client_for: ClientFor, make_user: MakeUser, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Seed one MCP audit entry via the service.
    customer = await client_for("c@example.com")
    user: PlatformUser = customer.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(customer))
    await _set_owner_mcp(session_factory, project_id, user.id, True)
    async with session_factory() as db:
        await McpService(db).list_projects(await _principal(user))

    import app.core.platform_security as sec

    await make_user("root@example.com", ADMIN)
    admin = await client_for("admin-reader@example.com", ADMIN, audience=sec.AUDIENCE_ADMIN)

    r = await admin.get("/admin/audit", params={"via": "api_token"})
    assert r.status_code == 200
    actions = {item["action"] for item in r.json()["items"]}
    assert "mcp.tool_call" in actions

    # The default (no via filter) is a superset of the api_token-only slice.
    all_r = await admin.get("/admin/audit")
    assert all_r.json()["total"] >= r.json()["total"]


# ── member MCP toggle endpoint ──────────────────────────────────────────────────────────


async def test_owner_can_toggle_member_mcp_flag(
    client: AsyncClient, client_for: ClientFor
) -> None:
    other = await client_for("mate@example.com")
    other_user: PlatformUser = other.user  # type: ignore[attr-defined]
    project_id = await make_project(client)
    r = await client.post(
        f"/projects/{project_id}/members",
        json={"email": "mate@example.com", "role": "editor"},
    )
    assert r.status_code == 201
    assert r.json()["mcp_enabled"] is False

    on = await client.patch(
        f"/projects/{project_id}/members/{other_user.id}/mcp",
        json={"mcp_enabled": True},
    )
    assert on.status_code == 200
    assert on.json()["mcp_enabled"] is True

    off = await client.patch(
        f"/projects/{project_id}/members/{other_user.id}/mcp",
        json={"mcp_enabled": False},
    )
    assert off.status_code == 200
    assert off.json()["mcp_enabled"] is False


async def test_non_owner_cannot_toggle_mcp_flag(
    client: AsyncClient, client_for: ClientFor
) -> None:
    editor = await client_for("ed@example.com")
    editor_user: PlatformUser = editor.user  # type: ignore[attr-defined]
    project_id = await make_project(client)
    await client.post(
        f"/projects/{project_id}/members",
        json={"email": "ed@example.com", "role": "editor"},
    )

    r = await editor.patch(
        f"/projects/{project_id}/members/{editor_user.id}/mcp",
        json={"mcp_enabled": True},
    )
    assert r.status_code == 403


async def test_add_member_can_pre_grant_mcp(client: AsyncClient, client_for: ClientFor) -> None:
    await client_for("mate@example.com")
    project_id = await make_project(client)
    r = await client.post(
        f"/projects/{project_id}/members",
        json={"email": "mate@example.com", "role": "editor", "mcp_enabled": True},
    )
    assert r.status_code == 201
    assert r.json()["mcp_enabled"] is True


# ── project-scoped token management (owner) ─────────────────────────────────────────────


async def test_owner_can_list_and_revoke_pinned_tokens(
    client: AsyncClient, anon_client: AsyncClient
) -> None:
    project_id = await make_project(client)
    created = await client.post(
        "/account/tokens",
        json={
            "name": "ci",
            "description": "MCP for CI",
            "scopes": ["mcp:read"],
            "project_id": project_id,
        },
    )
    assert created.status_code == 201
    token_id = created.json()["id"]
    raw = created.json()["token"]

    listed = (await client.get(f"/projects/{project_id}/tokens")).json()
    assert len(listed) == 1
    assert listed[0]["description"] == "MCP for CI"
    assert listed[0]["user_email"] == "primary@example.com"

    r = await client.delete(f"/projects/{project_id}/tokens/{token_id}")
    assert r.status_code == 204
    # Revoked token no longer works.
    pat = {"Authorization": f"Bearer {raw}"}
    assert (await anon_client.get("/projects", headers=pat)).status_code == 401


async def test_non_owner_cannot_see_project_tokens(
    client: AsyncClient, client_for: ClientFor
) -> None:
    other = await client_for("mate@example.com")
    project_id = await make_project(client)
    await client.post(
        f"/projects/{project_id}/members",
        json={"email": "mate@example.com", "role": "editor"},
    )
    r = await other.get(f"/projects/{project_id}/tokens")
    assert r.status_code == 403


async def test_project_tokens_filter_to_this_project(
    client: AsyncClient, client_for: ClientFor
) -> None:
    """A token pinned to another project is not listed under this project."""
    a = await make_project(client, "A")
    b = await make_project(client, "B")
    await client.post(
        "/account/tokens",
        json={"name": "for-b", "scopes": ["mcp:read"], "project_id": b},
    )
    listed = (await client.get(f"/projects/{a}/tokens")).json()
    assert listed == []


# ── admin token management ──────────────────────────────────────────────────────────────


async def test_admin_can_list_any_user_tokens(
    client: AsyncClient, client_for: ClientFor, make_user: MakeUser
) -> None:
    import app.core.platform_security as sec

    await client.post(
        "/account/tokens",
        json={"name": "t1", "scopes": ["read"]},
    )
    customer: PlatformUser = client.user  # type: ignore[attr-defined]
    await make_user("root@example.com", ADMIN)
    admin = await client_for("admin1@example.com", ADMIN, audience=sec.AUDIENCE_ADMIN)
    r = await admin.get(f"/admin/users/{customer.id}/tokens")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "t1"


async def test_admin_can_revoke_any_user_token(
    client: AsyncClient,
    anon_client: AsyncClient,
    client_for: ClientFor,
) -> None:
    import app.core.platform_security as sec

    created = (
        await client.post("/account/tokens", json={"name": "t1", "scopes": ["read"]})
    ).json()
    customer: PlatformUser = client.user  # type: ignore[attr-defined]
    admin = await client_for("admin2@example.com", ADMIN, audience=sec.AUDIENCE_ADMIN)
    r = await admin.delete(f"/admin/users/{customer.id}/tokens/{created['id']}")
    assert r.status_code == 204
    pat = {"Authorization": f"Bearer {created['token']}"}
    assert (await anon_client.get("/projects", headers=pat)).status_code == 401


async def test_non_admin_cannot_use_admin_token_endpoints(
    client: AsyncClient, client_for: ClientFor
) -> None:
    other = await client_for("mate@example.com")
    victim: PlatformUser = other.user  # type: ignore[attr-defined]
    r = await client.get(f"/admin/users/{victim.id}/tokens")
    assert r.status_code == 401


# ── scope and token checks for the MCP endpoint HTTP layer ─────────────────────────────


class _FakeCtx:
    """Minimal stand-in for a mcp.Context: only `headers` is read by _extract_token."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


async def test_extract_token_requires_bearer_scheme() -> None:
    with pytest.raises(AppError) as exc:
        mcp_api._extract_token(_FakeCtx({}))
    assert exc.value.status_code == 401

    with pytest.raises(AppError):
        mcp_api._extract_token(_FakeCtx({"authorization": "Basic abc"}))
    with pytest.raises(AppError):
        mcp_api._extract_token(_FakeCtx({"authorization": "Bearer   "}))

    assert mcp_api._extract_token(_FakeCtx({"Authorization": "Bearer tok"})) == "tok"
    assert mcp_api._extract_token(_FakeCtx({"AUTHORIZATION": "bearer tok2"})) == "tok2"


async def test_auth_rejects_non_pat_and_invalid_tokens(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await mcp_api._auth(
                _FakeCtx({"authorization": "Bearer not_a_pat_123"}),
                db,
                authz.SCOPE_MCP_READ,
            )
    assert exc.value.status_code == 401
    assert exc.value.code == "unauthenticated"

    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await mcp_api._auth(
                _FakeCtx({"authorization": "Bearer bb_pat_xxxxxxxxxx_fake"}),
                db,
                authz.SCOPE_MCP_READ,
            )
    assert exc.value.status_code == 401


async def test_auth_rejects_missing_mcp_scope(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = await client.post(
        "/account/tokens", json={"name": "readonly", "scopes": ["read"]}
    )
    raw = created.json()["token"]

    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await mcp_api._auth(
                _FakeCtx({"authorization": f"Bearer {raw}"}),
                db,
                authz.SCOPE_MCP_READ,
            )
    assert exc.value.status_code == 403
    assert exc.value.code == "insufficient_scope"


async def test_auth_accepts_token_with_mcp_scope(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = await client.post(
        "/account/tokens", json={"name": "mcpreader", "scopes": ["mcp:read"]}
    )
    raw = created.json()["token"]

    async with session_factory() as db:
        p = await mcp_api._auth(
            _FakeCtx({"authorization": f"Bearer {raw}"}),
            db,
            authz.SCOPE_MCP_READ,
        )
    assert p.via == "api_token"
    assert authz.SCOPE_MCP_READ in p.scopes


async def test_revoked_token_fails_auth(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = (
        await client.post(
            "/account/tokens", json={"name": "x", "scopes": ["mcp:read"]}
        )
    ).json()
    raw = created["token"]
    await client.delete(f"/account/tokens/{created['id']}")

    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await mcp_api._auth(
                _FakeCtx({"authorization": f"Bearer {raw}"}),
                db,
                authz.SCOPE_MCP_READ,
            )
    assert exc.value.status_code == 401


# ── cross-user isolation ────────────────────────────────────────────────────────────────


async def test_cross_user_isolation(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner: PlatformUser = client.user  # type: ignore[attr-defined]
    other = await client_for("mate@example.com")
    stranger: PlatformUser = other.user  # type: ignore[attr-defined]
    project_id = uuid.UUID(await make_project(client))
    await _set_owner_mcp(session_factory, project_id, owner.id, True)

    async with session_factory() as db:
        # Stranger cannot see anything about owner's project (looks missing).
        with pytest.raises(AppError) as exc:
            await McpService(db).get_project_spec(await _principal(stranger), project_id)
    assert exc.value.status_code == 404

    # After owner invites + enables MCP, stranger can see the project.
    await client.post(
        f"/projects/{project_id}/members",
        json={"email": "mate@example.com", "role": "editor"},
    )
    async with session_factory() as session:
        member = await session.get(ProjectMember, (project_id, stranger.id))
        assert member is not None
        member.mcp_enabled = True
        await session.commit()

    async with session_factory() as db:
        listed = await McpService(db).list_projects(await _principal(stranger))
    assert any(p["id"] == str(project_id) for p in listed)


# ── token "last_mcp_use_at" column ──────────────────────────────────────────────────────


async def test_last_mcp_use_at_column_exists(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The migration added last_mcp_use_at; a fresh token has it unset."""
    created = (
        await client.post(
            "/account/tokens", json={"name": "x", "scopes": ["mcp:read"]}
        )
    ).json()
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ApiToken).where(ApiToken.id == uuid.UUID(created["id"]))
            )
        ).scalar_one()
    assert row.last_mcp_use_at is None
    assert row.description is None
