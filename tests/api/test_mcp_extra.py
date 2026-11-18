"""MCP tools beyond the first 13 (app/services/mcp_extra.py): real permissions, auth config,
authorization, typed ops with dry run, behaviour blocks, undo ownership, destructive scope."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_authz as authz
from app.core.enums import FieldType
from app.exceptions import AppError
from app.models.enums import MemberRole, TokenAudience
from app.models.platform import PlatformUser, ProjectMember
from app.services.access_service import Principal
from app.services.mcp_extra import McpExtra
from tests.api._auth_helpers import make_entity, make_project

WRITE = (authz.SCOPE_MCP_READ, authz.SCOPE_MCP_WRITE)
DESTR = (*WRITE, authz.SCOPE_MCP_DESTRUCTIVE)
NOMAIL: dict[str, Any] = {"enabled": True, "email_magic_link_enabled": False}


def _p(user: PlatformUser, scopes: tuple[str, ...] = WRITE) -> Principal:
    return Principal(
        user=user, via="api_token", audience=TokenAudience.app, scopes=frozenset(scopes),
        token_project_id=None,
    )  # fmt: skip


async def _setup(
    client: AsyncClient, sf: async_sessionmaker[AsyncSession]
) -> tuple[PlatformUser, uuid.UUID]:
    user: PlatformUser = client.user  # type: ignore[attr-defined]
    pid = uuid.UUID(await make_project(client))
    async with sf() as s:
        m = await s.get(ProjectMember, (pid, user.id))
        assert m is not None
        m.mcp_enabled = True
        await s.commit()
    return user, pid


async def _entity(client: AsyncClient, pid: uuid.UUID, name: str = "Book") -> None:
    eid = await make_entity(client, str(pid), name)
    r = await client.post(
        f"/entities/{eid}/fields", json={"name": "title", "type": FieldType.string.value}
    )
    assert r.status_code == 201, r.text


async def test_set_permissions_really_saves(client: AsyncClient, session_factory: Any) -> None:
    user, pid = await _setup(client, session_factory)
    await _entity(client, pid)
    async with session_factory() as db:
        svc = McpExtra(db)
        await svc.set_auth_config(_p(user), pid, NOMAIL)
        await svc.create_role(_p(user), pid, {"name": "admin", "label": "Admin"})
        out = await svc.set_permissions(_p(user), pid, "Book", "create", ["admin"])
        assert out["status"] == "saved"
        got = await svc.list_roles_and_permissions(_p(user), pid)
    perms: list[dict[str, Any]] = got["permissions"]  # type: ignore[assignment]
    assert {"entity": "Book", "operation": "create", "roles": ["admin"], "row_rule": None} in perms


async def test_set_permissions_refuses_empty_roles_and_unknown_role(
    client: AsyncClient, session_factory: Any
) -> None:
    user, pid = await _setup(client, session_factory)
    await _entity(client, pid)
    async with session_factory() as db:
        svc = McpExtra(db)
        with pytest.raises(AppError) as exc:
            await svc.set_permissions(_p(user), pid, "Book", "list", [])
        assert exc.value.code == "empty_roles"
        with pytest.raises(AppError) as exc2:
            await svc.set_permissions(_p(user), pid, "Book", "list", ["nobody"])
        assert exc2.value.status_code == 422


async def test_auth_config_create_then_update_and_blocked_keys(
    client: AsyncClient, session_factory: Any
) -> None:
    user, pid = await _setup(client, session_factory)
    async with session_factory() as db:
        svc = McpExtra(db)
        a = await svc.set_auth_config(_p(user), pid, {**NOMAIL, "app_name": "Library"})
        assert a["enabled"] is True
        b = await svc.set_auth_config(_p(user), pid, {"access_token_ttl_minutes": 30})
        assert b["access_token_ttl_minutes"] == 30
        with pytest.raises(AppError) as exc:
            await svc.set_auth_config(_p(user), pid, {"suite": {}})
        assert exc.value.code == "not_allowed"


async def test_confirm_weakening_needs_destructive_scope(
    client: AsyncClient, session_factory: Any
) -> None:
    user, pid = await _setup(client, session_factory)
    await _entity(client, pid)
    async with session_factory() as db:
        svc = McpExtra(db)
        await svc.set_auth_config(_p(user), pid, NOMAIL)
        await svc.create_role(_p(user), pid, {"name": "admin", "label": "Admin"})
        await svc.set_permissions(_p(user), pid, "Book", "list", ["admin"])
        with pytest.raises(AppError) as exc:
            await svc.set_auth_config(_p(user), pid, {"enabled": False}, confirm_weakening=True)
        assert exc.value.status_code == 403
        # without the confirmation the access-widening edit is refused with a dashboard hint
        with pytest.raises(AppError) as weak:
            await svc.set_auth_config(_p(user), pid, {"enabled": False})
        assert weak.value.code == "access_weakened"
        assert "dashboard" in weak.value.message
        # with the destructive scope it goes through
        out = await svc.set_auth_config(
            _p(user, DESTR), pid, {"enabled": False}, confirm_weakening=True
        )
        assert out["enabled"] is False


async def test_apply_op_dry_run_then_real_and_destructive_split(
    client: AsyncClient, session_factory: Any
) -> None:
    user, pid = await _setup(client, session_factory)
    async with session_factory() as db:
        svc = McpExtra(db)
        entity = {"entity": {"name": "Author", "fields": [{"name": "name", "type": "string"}]}}
        dry = await svc.apply_op(_p(user), pid, "add_entity", entity, dry_run=True)
        assert dry["dry_run"] is True and dry["would_change"]["entities_added"] == ["Author"]  # type: ignore[index]
        spec = await svc.get_data_model(_p(user), pid)
        assert spec["entities"] == []
        real = await svc.apply_op(_p(user), pid, "add_entity", entity)
        assert real["applied"] is True
        # a removal through the normal tool is refused ...
        with pytest.raises(AppError) as exc:
            await svc.apply_op(_p(user), pid, "remove_entity", {"name": "Author"})
        assert exc.value.code == "destructive_op"
        # ... and the destructive tool needs the scope on the token, plus is a dry run first
        dry2 = await svc.apply_op(
            _p(user, DESTR),
            pid,
            "remove_entity",
            {"name": "Author"},
            dry_run=True,
            destructive=True,
        )
        assert dry2["would_change"]["entities_removed"] == ["Author"]  # type: ignore[index]
        done = await svc.apply_op(
            _p(user, DESTR), pid, "remove_entity", {"name": "Author"}, destructive=True
        )
        assert done["applied"] is True


async def test_undo_only_reverts_own_mcp_change(client: AsyncClient, session_factory: Any) -> None:
    user, pid = await _setup(client, session_factory)
    await _entity(client, pid, "Thing")  # made through the REST routes (actor: user), not MCP
    async with session_factory() as db:
        svc = McpExtra(db)
        with pytest.raises(AppError) as exc:
            await svc.undo_last_change(_p(user), pid)
        assert exc.value.code == "not_your_change"
        await svc.apply_op(
            _p(user),
            pid,
            "add_entity",
            {"entity": {"name": "Mine", "fields": [{"name": "x", "type": "string"}]}},
        )
        out = await svc.undo_last_change(_p(user), pid)
        assert out["done"] == "undo"
        names = {e["name"] for e in (await svc.get_data_model(_p(user), pid))["entities"]}  # type: ignore[union-attr]
        assert names == {"Thing"}
        assert (await svc.redo_last_change(_p(user), pid))["done"] == "redo"


async def test_behavior_block_and_hook_effects_owner_only(
    client: AsyncClient, session_factory: Any
) -> None:
    user, pid = await _setup(client, session_factory)
    async with session_factory() as db:
        svc = McpExtra(db)
        out = await svc.put_behavior_block(_p(user), pid, "api_edge", {})
        assert "api_edge" in out
        with pytest.raises(AppError) as bad:
            await svc.put_behavior_block(_p(user), pid, "nope", {})
        assert bad.value.code == "unknown_block"
    async with session_factory() as s:  # demote to editor: hook_effects must now be refused
        m = await s.get(ProjectMember, (pid, user.id))
        assert m is not None
        m.role = MemberRole.editor
        await s.commit()
    async with session_factory() as db:
        with pytest.raises(AppError) as exc:
            await McpExtra(db).put_behavior_block(_p(user), pid, "hook_effects", {"enabled": False})
        assert exc.value.status_code == 403


async def test_status_history_and_op_types(client: AsyncClient, session_factory: Any) -> None:
    user, pid = await _setup(client, session_factory)
    async with session_factory() as db:
        svc = McpExtra(db)
        status = await svc.get_project_status(_p(user), pid)
        assert "next_step" in status
        types = {t["op_type"]: t["destructive"] for t in await svc.list_op_types(_p(user), pid)}  # type: ignore[misc]
        assert types["remove_field"] is True and types["add_field"] is False
        await svc.apply_op(
            _p(user),
            pid,
            "add_entity",
            {"entity": {"name": "Alpha", "fields": [{"name": "x", "type": "string"}]}},
        )
        hist = await svc.list_spec_history(_p(user), pid)
        assert hist["total"] == 1
        assert (await svc.list_generations(_p(user), pid))["total"] == 0


async def test_put_packs_dry_run_default_and_scope(
    client: AsyncClient, session_factory: Any
) -> None:
    user, pid = await _setup(client, session_factory)
    async with session_factory() as db:
        svc = McpExtra(db)
        # the destructive tool is only reachable with the scope (checked by the tool wrapper);
        # at service level an unknown pack key is refused before anything is read or written
        with pytest.raises(AppError) as exc:
            await svc.put_packs(_p(user, DESTR), pid, {"nonsense": {}})
        assert exc.value.code == "invalid_input"
        dry = await svc.put_packs(_p(user, DESTR), pid, {"booking": {}})
        assert dry["dry_run"] is True and dry["applied"] is False
