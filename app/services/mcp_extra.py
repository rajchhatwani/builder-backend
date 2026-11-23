"""MCP tools beyond the first 13: everything the dashboard's non-secret screens can do.

Same rules as McpService (membership + mcp_enabled + editor role + plan + audit per call). Added rules:
  - the tools call the SAME services as the dashboard routes, so validation, the op-log and the
    "this gives a role more access" check (409 access_weakened) are identical;
  - `confirm_weakening` and the destructive ops need the separate `mcp:destructive` token scope;
    without it an access-widening edit is refused with a message that points at the dashboard;
  - never reachable here: credentials (auth secrets, provider keys), members/tokens/MCP grants,
    project delete, billing, admin. Effectful hooks (`hook_effects`) need the project OWNER, exactly
    like the dashboard route.
"""

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.core import platform_authz as authz
from app.core.validation import validate
from app.exceptions import AppError
from app.models.entity import Entity
from app.models.enums import MemberRole
from app.models.platform import ProjectMember
from app.schemas import behavior as bs
from app.schemas.auth_config import AuthConfigCreate, AuthConfigRead, AuthConfigUpdate
from app.schemas.authorization import AuthorizationRead, AuthorizationWrite
from app.schemas.project_permission import PermissionEntry, ProjectPermissionBulkUpsert
from app.schemas.project import ProjectCreate
from app.schemas.project_role import ProjectRoleCreate, ProjectRoleUpdate
from app.services.access_service import Principal
from app.services.auth_config_service import AuthConfigService
from app.services.authorization_service import AuthorizationService
from app.services.behavior_service import BehaviorService
from app.services.generation_service import GenerationService
from app.services import mcp_secrets
from app.services.mcp_service import McpService, _cap_dict, _cap_list
from app.services.ops.registry import REGISTRY, plan
from app.services.ops.service import OpsService
from app.services.project_permission_service import ProjectPermissionService
from app.services.project_role_service import ProjectRoleService
from app.services.spec_service import SpecService
from app.services.status_service import StatusService

# Ops that remove things or rewrite the whole model: only through the destructive tool.
DESTRUCTIVE_OPS = frozenset(
    {"remove_entity", "remove_field", "remove_relation", "remove_custom_field", "replace_spec"}
)
# Behaviour blocks written through put_behavior_block (same set the dashboard saves one by one).
BLOCKS: dict[str, str] = {
    "events": "Events",
    "providers": "Providers",
    "notifications": "Notifications",
    "jobs": "Jobs",
    "workflows": "Workflows",
    "api_edge": "ApiEdge",
    "webhooks": "Webhooks",
    "hook_effects": "HookEffects",  # owner only, like PUT /behavior/hook-effects
}
# Auth-config keys the MCP never sets (identity federation is configured by a person).
_AUTH_BLOCKED = frozenset({"suite", "confirm_weakening"})
_ROLE_KEYS = ("label", "is_default", "self_assignable", "invite_only", "inherits_from", "position")
_WEAKENED_HINT = (
    "this gives a role more access than it has now. Review it in the dashboard (Access matrix, "
    "Visual spec diff), or repeat with confirm_weakening=true using a token that has the "
    "'mcp:destructive' scope."
)


def _bad(code: str, message: str, status: int = 422, details: list[Any] | None = None) -> AppError:
    return AppError(code=code, message=message, status_code=status, details=details)


def _validation_error(exc: ValidationError) -> AppError:
    """Paths and messages only, never the submitted values."""
    return _bad(
        "invalid_input",
        "the input does not match the expected shape",
        details=[
            {"path": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
            for e in exc.errors(include_input=False, include_url=False, include_context=False)
        ][:20],
    )


def _diff(before: Any, after: Any) -> dict[str, Any]:
    """A short, human-readable summary of what an operation changes."""
    b, a = before.model_dump(mode="json"), after.model_dump(mode="json")
    out: dict[str, Any] = {"sections_changed": sorted(k for k in a if a.get(k) != b.get(k))}
    be = {e["name"]: e for e in b.get("entities", [])}
    ae = {e["name"]: e for e in a.get("entities", [])}
    if set(be) != set(ae):
        out["entities_added"] = sorted(set(ae) - set(be))
        out["entities_removed"] = sorted(set(be) - set(ae))
    fields: dict[str, Any] = {}
    for name in sorted(set(be) & set(ae)):
        bf = {f["name"] for f in be[name].get("fields", [])}
        af = {f["name"] for f in ae[name].get("fields", [])}
        if bf != af:
            fields[name] = {"added": sorted(af - bf), "removed": sorted(bf - af)}
    if fields:
        out["fields_changed"] = fields
    return out


class McpExtra(McpService):
    # -- small helpers -----------------------------------------------------------------

    def _confirm(self, principal: Principal, requested: bool) -> bool:
        """confirm_weakening is honoured only for a token that has mcp:destructive."""
        if not requested:
            return False
        if authz.SCOPE_MCP_DESTRUCTIVE not in principal.scopes:
            raise _bad(
                "insufficient_scope",
                "confirm_weakening needs the 'mcp:destructive' scope on your API token",
                403,
            )
        return True

    async def _editor(self, principal: Principal, project_id: uuid.UUID) -> Any:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        return member

    @staticmethod
    def _reraise_weakened(exc: AppError) -> AppError:
        if exc.code == "access_weakened":
            return AppError(
                code="access_weakened",
                message=_WEAKENED_HINT,
                status_code=409,
                details=exc.details,
            )
        return exc

    # -- reads -------------------------------------------------------------------------

    async def list_op_types(
        self, principal: Principal, project_id: uuid.UUID
    ) -> list[dict[str, object]]:
        await self._resolve_membership(principal, project_id)
        rows = [
            {
                "op_type": name,
                "destructive": name in DESTRUCTIVE_OPS,
                "payload_schema": d.model.model_json_schema(),
            }
            for name, d in sorted(REGISTRY.items())
        ]
        return _cap_list(rows)

    async def list_spec_history(
        self, principal: Principal, project_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        limit = max(1, min(limit, 50))
        items, total = await OpsService(self.db).list_ops(project_id, limit, max(0, offset))
        slim = [
            {
                "seq": i.seq,
                "op_type": i.op_type,
                "origin": i.origin,
                "actor": i.actor.kind,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ]
        return _cap_dict({"total": total, "items": slim})

    async def get_project_status(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        """The dashboard's readiness board: issues per section and the one next step."""
        await self._resolve_membership(principal, project_id)
        status = await StatusService(self.db).get(project_id)
        spec = await SpecService(self.db).assemble(project_id)
        out = status.model_dump(mode="json")
        out["missing"] = mcp_secrets.missing_items(spec, status.issues)
        out["secrets_needed"] = mcp_secrets.secrets_needed(spec)
        out["missing_summary"] = (
            "nothing missing except secrets a human must enter"
            if not [m for m in out["missing"] if m["who"] == "tool"]
            else "items with who=tool can be fixed with the listed next_tools"
        )
        return _cap_dict(out)

    async def list_secrets_needed(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        """What a human must enter (names and where only, never values)."""
        await self._resolve_membership(principal, project_id)
        spec = await SpecService(self.db).assemble(project_id)
        items = mcp_secrets.secrets_needed(spec)
        await self._audit(principal, "list_secrets_needed", project_id)
        return _cap_dict(
            {
                "secrets_needed": items,
                "note": "Names and locations only. Never send a value through MCP; tell the "
                "user to enter these in the dashboard.",
            }
        )

    async def list_generations(
        self, principal: Principal, project_id: uuid.UUID, limit: int = 10
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        items, total = await GenerationService(self.db).list(project_id, max(1, min(limit, 50)), 0)
        return _cap_dict({"total": total, "items": [i.model_dump(mode="json") for i in items]})

    async def list_roles_and_permissions(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        entity: str | None = None,
        role: str | None = None,
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        roles, _ = await ProjectRoleService(self.db).list(project_id, 200, 0)
        perms = await ProjectPermissionService(self.db)._list_all(project_id)
        names = {
            e.id: e.name
            for e in (
                await self.db.execute(select(Entity).where(Entity.project_id == project_id))
            ).scalars()
        }
        if entity is not None and entity not in names.values():
            raise _bad("not_found", f"entity '{entity}' not found", 404)
        rows = [
            {
                "entity": names.get(p.entity_id, "?"),
                "operation": str(p.operation),
                "roles": list(p.roles),
                "row_rule": str(p.row_rule) if p.row_rule else None,
            }
            for p in perms
        ]
        if entity is not None:
            rows = [r for r in rows if r["entity"] == entity]
        if role is not None:
            rows = [r for r in rows if role in r["roles"]]  # type: ignore[operator]
        return _cap_dict(
            {
                "roles": [
                    {
                        "name": r.name,
                        "label": r.label,
                        "is_default": r.is_default,
                        "self_assignable": r.self_assignable,
                        "invite_only": r.invite_only,
                        "inherits_from": r.inherits_from,
                        "position": r.position,
                    }
                    for r in roles
                ],
                "permissions": rows,
            }
        )

    # -- projects ----------------------------------------------------------------------

    async def create_project(
        self,
        principal: Principal,
        name: str,
        description: str = "",
        slug: str | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> dict[str, object]:
        """Create a project the way POST /projects does (same org membership, plan cap, slug
        rules) and switch MCP on for the creator so the other tools can see it."""
        from app.api.security import org_deletion_pending, org_mfa_required
        from app.models.platform import Organization, OrganizationMember
        from app.services.organization_service import OrganizationService
        from app.services.project_service import ProjectService

        if principal.token_project_id is not None:
            raise _bad(
                "pinned_token",
                "this API token is pinned to one project and cannot create new ones",
                403,
            )
        try:
            body = ProjectCreate(
                name=name,
                slug=slug,
                description=description or None,
                organization_id=organization_id,
            )
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        user = principal.user
        target = organization_id or user.default_organization_id
        if target is not None:
            org = await self.db.get(Organization, target)
            member = await self.db.get(OrganizationMember, (target, user.id))
            # A stranger skips these checks and gets the same 403 from the service as the REST route.
            if org is not None and member is not None:
                if org.deletion_requested_at is not None:
                    raise org_deletion_pending(org)
                if org.require_mfa and not principal.mfa_satisfied:
                    raise org_mfa_required(org, principal)
                orgs = OrganizationService(self.db)
                plan, _sub = await orgs.plan_and_subscription(org.id)
                if not plan.allow_mcp:
                    raise await orgs.deny_mcp_not_in_plan(
                        org.id, plan, actor_id=user.id, actor_email=user.email
                    )
        user_id = user.id
        project = await ProjectService(self.db).create(body, user, organization_id=organization_id)
        await self.db.refresh(project)  # the commit inside create() may have expired it
        project_id, p_name, p_slug, p_org = project.id, project.name, project.slug, (
            project.organization_id
        )  # fmt: skip
        member_row = await self.db.get(ProjectMember, (project_id, user_id))
        if member_row is not None:
            member_row.mcp_enabled = True
        await self._audit(principal, "create_project", project_id, extra={"name": name[:100]})
        await self.db.commit()
        return {
            "id": str(project_id),
            "name": p_name,
            "slug": p_slug,
            "organization_id": str(p_org) if p_org else None,
            "your_role": "owner",
            "mcp_enabled": True,
            "next_tools": ["create_entity", "get_project_status"],
        }

    # -- spec operations ---------------------------------------------------------------

    async def apply_op(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        op_type: str,
        payload: dict[str, Any],
        *,
        dry_run: bool = False,
        confirm_weakening: bool = False,
        destructive: bool = False,
    ) -> dict[str, object]:
        """One typed spec operation. `destructive=True` is the mcp:destructive tool: it allows the
        remove_* / replace_spec ops and, with `dry_run=False`, applies them."""
        await self._editor(principal, project_id)
        if op_type in DESTRUCTIVE_OPS and not destructive:
            raise _bad(
                "destructive_op",
                f"'{op_type}' removes or rewrites model data; use apply_destructive_op (mcp:destructive scope)",
                403,
            )
        if destructive and op_type not in DESTRUCTIVE_OPS:
            raise _bad("not_destructive", f"'{op_type}' is not destructive; use apply_op", 422)
        confirm = self._confirm(principal, confirm_weakening)
        try:
            if dry_run:
                before = await SpecService(self.db).assemble(project_id)
                planned = plan(before, op_type, payload)
                known = {(i.path, i.code, i.message) for i in validate(before)}
                fresh = [
                    i for i in validate(planned.after) if (i.path, i.code, i.message) not in known
                ]
                result: dict[str, object] = {
                    "dry_run": True,
                    "op_type": op_type,
                    "would_change": _diff(before, planned.after),
                    "new_validation_issues": [i.model_dump() for i in fresh][:20],
                    "applied": False,
                }
                await self._audit(
                    principal, "apply_op.dry_run", project_id, extra={"op_type": op_type}
                )
                return _cap_dict(result)
            applied = await OpsService(self.db).apply_op(
                project_id, op_type, payload, self._actor(principal), confirm_weakening=confirm
            )
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        await self._audit(
            principal, "apply_op", project_id, extra={"op_type": op_type, "seq": applied.op.seq}
        )
        return _cap_dict(
            {
                "applied": True,
                "seq": applied.op.seq,
                "op_type": op_type,
                "spec_hash": applied.op.spec_hash_after,
            }
        )

    async def _undo_redo(
        self, principal: Principal, project_id: uuid.UUID, kind: str, confirm_weakening: bool
    ) -> dict[str, object]:
        await self._editor(principal, project_id)
        confirm = self._confirm(principal, confirm_weakening)
        ops = OpsService(self.db)
        rows = await ops._rows(project_id)
        undo, redo = ops.stacks(rows)
        stack = undo if kind == "undo" else redo
        if stack:
            target = next(r for r in rows if r.seq == stack[-1])
            # Never revert somebody else's change: the target must be this person's own MCP edit.
            if target.actor_kind != "mcp" or target.actor_id != principal.user.id:
                raise _bad(
                    "not_your_change",
                    f"the latest change to {kind} was not made by you through MCP; use the dashboard history",
                    409,
                )
        try:
            applied = await (ops.undo if kind == "undo" else ops.redo)(
                project_id, self._actor(principal), confirm_weakening=confirm
            )
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        await self._audit(principal, kind, project_id, extra={"seq": applied.op.seq})
        return {"done": kind, "seq": applied.op.seq}

    async def undo_last_change(
        self, principal: Principal, project_id: uuid.UUID, confirm_weakening: bool = False
    ) -> dict[str, object]:
        return await self._undo_redo(principal, project_id, "undo", confirm_weakening)

    async def redo_last_change(
        self, principal: Principal, project_id: uuid.UUID, confirm_weakening: bool = False
    ) -> dict[str, object]:
        return await self._undo_redo(principal, project_id, "redo", confirm_weakening)

    # -- behaviour blocks --------------------------------------------------------------

    async def put_behavior_block(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        block: str,
        value: Any,
        expected_version: int | None = None,
    ) -> dict[str, object]:
        member = await self._editor(principal, project_id)
        if block not in BLOCKS:
            raise _bad("unknown_block", f"block must be one of {sorted(BLOCKS)}")
        if block == "hook_effects" and member.role != MemberRole.owner:
            raise _bad("forbidden", "only the project owner may change effectful hooks", 403)
        write_cls = getattr(bs, BLOCKS[block] + "Write")
        try:
            body = write_cls(**{block: value, "expected_version": expected_version})
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        out = await BehaviorService(self.db).put_block(
            project_id, block, getattr(body, block), body.expected_version
        )
        await self._audit(principal, "put_behavior_block", project_id, extra={"block": block})
        return _cap_dict(dict(out))

    # -- roles, permissions, auth, authorization ---------------------------------------

    async def create_role(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        role: dict[str, Any],
        upsert: bool = False,
        confirm_weakening: bool = False,
    ) -> dict[str, object]:
        await self._editor(principal, project_id)
        confirm = self._confirm(principal, confirm_weakening)
        if upsert and isinstance(role.get("name"), str):
            existing = await ProjectRoleService(self.db)._get_role_by_name(project_id, role["name"])
            if existing is not None:
                changes = {k: v for k, v in role.items() if k != "name"}
                return await self._update_role(
                    principal, project_id, role["name"], changes, confirm
                )
        try:
            data = ProjectRoleCreate(**{**role, "confirm_weakening": confirm})
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        try:
            created = await ProjectRoleService(self.db).create(project_id, data)
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        out = {"name": created.name, "label": created.label, "status": "created"}
        await self._audit(principal, "create_role", project_id, extra={"role": out["name"]})
        return _cap_dict(out)

    async def update_role(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        name: str,
        changes: dict[str, Any],
        confirm_weakening: bool = False,
    ) -> dict[str, object]:
        await self._editor(principal, project_id)
        confirm = self._confirm(principal, confirm_weakening)
        return await self._update_role(principal, project_id, name, changes, confirm)

    async def _update_role(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        name: str,
        changes: dict[str, Any],
        confirm: bool,
    ) -> dict[str, object]:
        unknown = sorted(set(changes) - set(_ROLE_KEYS))
        if unknown:
            raise _bad(
                "unknown_keys",
                f"unknown role keys {unknown}; allowed keys: {list(_ROLE_KEYS)}",
            )
        svc = ProjectRoleService(self.db)
        row = await svc._get_role_by_name(project_id, name)
        if row is None:
            raise _bad("not_found", f"role '{name}' not found", 404)
        role_id = row.id
        try:
            body = ProjectRoleUpdate(**changes, confirm_weakening=confirm)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        try:
            r = await svc.update(role_id, body)
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        out = {
            "name": r.name,
            "label": r.label,
            "is_default": r.is_default,
            "self_assignable": r.self_assignable,
            "invite_only": r.invite_only,
            "inherits_from": r.inherits_from,
            "position": r.position,
            "status": "updated",
        }
        await self._audit(
            principal, "update_role", project_id, extra={"role": name, "keys": sorted(changes)}
        )
        return _cap_dict(out)

    async def set_permissions(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        entity_name: str,
        operation: str,
        roles: list[str],
        row_rule: str | None = None,
        confirm_weakening: bool = False,
    ) -> dict[str, object]:
        """Really saves one (entity, operation) slot of the role matrix. Roles must exist
        (create_role). An empty role list would make the slot PUBLIC, so it is refused here."""
        await self._editor(principal, project_id)
        if not roles:
            raise _bad(
                "empty_roles",
                "roles must name at least one role (an empty list would make this operation public)",
            )
        confirm = self._confirm(principal, confirm_weakening)
        ent = (
            await self.db.execute(
                select(Entity).where(Entity.project_id == project_id, Entity.name == entity_name)
            )
        ).scalar_one_or_none()
        if ent is None:
            raise _bad("not_found", f"entity '{entity_name}' not found", 404)
        try:
            body = ProjectPermissionBulkUpsert(
                permissions=[
                    PermissionEntry.model_validate(
                        {
                            "entity_id": ent.id,
                            "operation": operation,
                            "roles": roles,
                            "row_rule": row_rule,
                        }
                    )
                ],
                confirm_weakening=confirm,
            )
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        try:
            await ProjectPermissionService(self.db).bulk_upsert(project_id, body)
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        await self._audit(
            principal,
            "set_permissions",
            project_id,
            extra={"entity": entity_name, "operation": operation},
        )
        return _cap_dict(
            {
                "entity": entity_name,
                "operation": operation,
                "roles": roles,
                "row_rule": row_rule,
                "status": "saved",
            }
        )

    async def set_auth_config(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        config: dict[str, Any],
        confirm_weakening: bool = False,
    ) -> dict[str, object]:
        """Create or update the project's sign-in settings (non-secret). Credentials for e-mail/SMS
        are set by a person in the dashboard; `suite` identity is not settable here."""
        await self._editor(principal, project_id)
        blocked = sorted(set(config) & _AUTH_BLOCKED)
        if blocked:
            raise _bad("not_allowed", f"these keys cannot be set through MCP: {blocked}")
        valid = set(AuthConfigCreate.model_fields) | set(AuthConfigUpdate.model_fields)
        unknown = sorted(set(config) - valid)
        if unknown:
            raise _bad(
                "unknown_keys",
                f"unknown auth keys {unknown}; valid keys: {sorted(valid - _AUTH_BLOCKED)}. "
                "Roles are managed with create_role / update_role, not here.",
            )
        confirm = self._confirm(principal, confirm_weakening)
        service = AuthConfigService(self.db)
        try:
            try:
                await service.get(project_id)
                exists = True
            except AppError as exc:
                if exc.status_code != 404:
                    raise
                exists = False
            if exists:
                row = await service.update(
                    project_id, AuthConfigUpdate(**config, confirm_weakening=confirm)
                )
            else:
                row = await service.create(project_id, AuthConfigCreate(**config))
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        await self._audit(
            principal, "set_auth_config", project_id, extra={"keys": sorted(config)[:30]}
        )
        return _cap_dict(AuthConfigRead.model_validate(row).model_dump(mode="json"))

    async def set_authorization(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        authorization: dict[str, Any],
        confirm_weakening: bool = False,
    ) -> dict[str, object]:
        """Replace the authorization model, policies, attachments and field access (same as the
        dashboard's Authorization page)."""
        await self._editor(principal, project_id)
        confirm = self._confirm(principal, confirm_weakening)
        try:
            body = AuthorizationWrite(**{**authorization, "confirm_weakening": confirm})
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        try:
            out: AuthorizationRead = await AuthorizationService(self.db).put(project_id, body)
        except AppError as exc:
            raise self._reraise_weakened(exc) from exc
        await self._audit(principal, "set_authorization", project_id)
        return _cap_dict(out.model_dump(mode="json"))

    async def put_packs(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        packs: dict[str, Any] | None,
        *,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Set `spec.packs` as a whole. No platform route writes packs today, so this is a
        whole-spec replace through the op-log (undoable); destructive scope, dry run by default."""
        from app.core.spec_models import SpecPacks

        await self._editor(principal, project_id)
        try:
            new_packs = SpecPacks.model_validate(packs) if packs is not None else None
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        spec = await SpecService(self.db).assemble(project_id)
        spec.packs = new_packs
        return await self.apply_op(
            principal,
            project_id,
            "replace_spec",
            {"spec": spec.model_dump(mode="json")},
            dry_run=dry_run,
            destructive=True,
        )
