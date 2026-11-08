"""S! (security-weakening or data-removing spec edits), C! (dependency request) and E (external effect).

None of these acts HERE. S! and E only return an ApprovalRequest that describes exactly what would run
(`op_type` / `action` + the arguments); once a human approved it, `approved_effects.execute` runs exactly
that, server-side, bound to the approval's spec hash, content hash and payload hash (B-002).
request_dependency records a *request* with the dependency policy service and never installs."""

from typing import Any

from app.exceptions import AppError
from app.services.agent.contract import (
    ApprovalKind,
    ApprovalRequest,
    PermissionClass,
    Tool,
    ToolContext,
    ToolResult,
)
from app.services.dependency_policy_service import DependencyPolicyService, normalize_name

from ._common import app_error_failure


def _ask(kind: ApprovalKind, subject: str, **payload: Any) -> Any:
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"status": "approval_required", "executed": False},
            approval=ApprovalRequest(kind, subject, {**payload, **args, "run_id": str(ctx.run_id)}),
        )

    return handler


def _s_bang(op_type: str, subject: str) -> Any:
    return _ask(ApprovalKind.D, subject, op_type=op_type)


async def request_dependency(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    try:
        row, created = await DependencyPolicyService(ctx.session).request(
            ctx.project_id, args["name"], args["version"], args["reason"], list(args.get("hashes", [])), ctx.actor.user_id
        )
    except AppError as exc:
        if exc.code == "dependency_already_allowed":
            return ToolResult(ok=True, data={"status": "active", "package": normalize_name(args["name"]),
                                             "version": args["version"], "installed": False})  # fmt: skip
        return ToolResult(ok=False, failures=(app_error_failure("request_dependency", exc),))
    return ToolResult(
        ok=True,
        data={"status": row.status, "package": row.package, "version": row.version, "installed": False,
              "new_request": created},  # fmt: skip
        approval=ApprovalRequest(
            ApprovalKind.D,
            f"dependency {row.package}=={row.version} is not on the allow-list",
            {"package": row.package, "version": row.version, "reason": args["reason"][:500],
             "request_id": str(row.id), "run_id": str(ctx.run_id)},
        ),
    )


async def _scope_dependency(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    try:
        name = normalize_name(args["name"])
    except ValueError:
        name = str(args["name"])
    return None if name in ctx.plan.dependencies else ("dependency", name)


async def _scope_entity(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    name = str(args["entity"] if "entity" in args else args["name"])
    return None if name in ctx.plan.entities else ("entity", name)


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_NAME = {"type": "string", "minLength": 1, "maxLength": 80}
_WHY = {"type": "string", "minLength": 1, "maxLength": 500}
SB, E = PermissionClass.S_BANG, PermissionClass.E
TOOLS: list[Tool] = [
    Tool("remove_entity", "Ask a human to remove an entity and its data. Never executes.",
         _obj({"name": _NAME, "reason": _WHY}, ["name", "reason"]), SB,
         _s_bang("remove_entity", "remove an entity and its data")),
    Tool("remove_field", "Ask a human to remove a field and its data. Never executes.",
         _obj({"entity": _NAME, "name": _NAME, "reason": _WHY}, ["entity", "name", "reason"]), SB,
         _s_bang("remove_field", "remove a field and its data")),
    Tool("change_tenancy_mode", "Ask a human to change the tenancy mode. Never executes.",
         _obj({"mode": {"type": "string", "enum": ["single", "multi"]}, "reason": _WHY}, ["mode", "reason"]), SB,
         _s_bang("change_tenancy_mode", "change the tenancy mode")),
    Tool("weaken_access_rule", "Ask a human to loosen an access rule. Never executes.",
         _obj({"entity": _NAME, "role": _NAME, "action": _NAME, "reason": _WHY},
              ["entity", "role", "action", "reason"]), SB,
         _s_bang("weaken_access_rule", "loosen an access rule")),
    Tool("request_dependency", "Request a library. Allow-listed ones are active; others need a human.",
         _obj({"name": _NAME, "version": {"type": "string", "minLength": 1, "maxLength": 40}, "reason": _WHY,
               "hashes": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 80}}},
              ["name", "version", "reason"]), PermissionClass.C_BANG, request_dependency),
    Tool("apply_migration", "Ask for approval to apply the migration to the dev environment.",
         _obj({"env": {"type": "string", "enum": ["dev"]}}, ["env"]), E,
         _ask(ApprovalKind.E, "apply the migration to the dev environment", action="apply_migration")),
    Tool("create_pr", "Ask for approval to open a pull request.",
         _obj({"title": {"type": "string", "minLength": 1, "maxLength": 200}}, ["title"]), E,
         _ask(ApprovalKind.E, "open a pull request", action="create_pr")),
    Tool("request_secret", "Ask a human to provide a secret by name. You never see its value.",
         _obj({"name": _NAME}, ["name"]), E, _ask(ApprovalKind.E, "provide a secret", action="request_secret")),
    Tool("fetch_docs", "Ask for approval to fetch a documentation page.",
         _obj({"url": {"type": "string", "minLength": 1, "maxLength": 500}}, ["url"]), E,
         _ask(ApprovalKind.E, "fetch a documentation page", action="fetch_docs")),
]  # fmt: skip
SCOPES: dict[str, Any] = {
    "remove_entity": _scope_entity,
    "remove_field": _scope_entity,
    "weaken_access_rule": _scope_entity,
    "request_dependency": _scope_dependency,
}
