"""What an MCP client can learn about the platform without prior knowledge (MCP-M1).

`describe_platform` is built from the REAL registries (Spec fields, SpecPacks fields, behaviour
blocks, spec-op registry), so it cannot drift from the code; the hand-written parts are the tool
mapping (TOOL_HELP / SECTION_TOOLS) and tests pin them against the registered tools and Spec.
`get_started` is the ordered playbook; `error_payload` is the uniform error shape.
Nothing here touches the database, secrets or other tenants.
"""

import types
import typing
from typing import Any

from pydantic import BaseModel

from app.core.spec_models import Spec, SpecPacks
from app.exceptions import AppError
from app.services.mcp_extra import BLOCKS, DESTRUCTIVE_OPS
from app.services.ops.registry import REGISTRY

# tool -> scope, one example call, tools that usually come next. Every registered tool must be here
# (tests/api/test_mcp_catalog.py), and every name in `next` must be a registered tool.
TOOL_HELP: dict[str, dict[str, Any]] = {
    "describe_platform": {
        "scope": "mcp:read",
        "example": '{"topic": "packs"}',
        "next": ["get_started", "list_projects"],
    },
    "get_started": {
        "scope": "mcp:read",
        "example": "{}",
        "next": ["list_projects", "describe_platform"],
    },
    "list_projects": {
        "scope": "mcp:read",
        "example": "{}",
        "next": ["get_project_status", "get_data_model"],
    },
    "get_project_spec": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid from list_projects>"}',
        "next": ["apply_op", "put_behavior_block"],
    },
    "get_data_model": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["create_entity", "add_field"],
    },
    "get_openapi": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["get_frontend_contract", "generate_project"],
    },
    "get_auth_model": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["set_auth_config", "create_role"],
    },
    "get_frontend_contract": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["generate_project"],
    },
    "get_deploy_info": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["get_project_status"],
    },
    "list_secrets_needed": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["get_project_status", "generate_project"],
    },
    "validate_spec": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["get_project_status", "generate_project"],
    },
    "list_op_types": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["apply_op"],
    },
    "list_spec_history": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>", "limit": 10}',
        "next": ["undo_last_change"],
    },
    "get_project_status": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["validate_spec", "generate_project"],
    },
    "list_roles_and_permissions": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>"}',
        "next": ["create_role", "set_permissions"],
    },
    "list_generations": {
        "scope": "mcp:read",
        "example": '{"project_id": "<uuid>", "limit": 5}',
        "next": ["generate_project"],
    },
    "create_entity": {
        "scope": "mcp:write",
        "example": '{"project_id": "<uuid>", "name": "Patient"}',
        "next": ["add_field", "add_relation"],
    },
    "add_field": {
        "scope": "mcp:write",
        "example": (
            '{"project_id": "<uuid>", "entity_name": "Patient", '
            '"field": {"name": "email", "type": "string", "required": true, "unique": true}}'
        ),
        "next": ["add_relation", "validate_spec"],
    },
    "add_relation": {
        "scope": "mcp:write",
        "example": (
            '{"project_id": "<uuid>", "relation": {"kind": "one_to_many", '
            '"from_entity_id": "<uuid>", "to_entity_id": "<uuid>", '
            '"from_name": "appointments", "to_name": "patient"}}'
        ),
        "next": ["create_role", "validate_spec"],
    },
    "set_permissions": {
        "scope": "mcp:write",
        "example": (
            '{"project_id": "<uuid>", "entity_name": "Patient", "operation": "list", '
            '"roles": ["admin"], "row_rule": "owner"}'
        ),
        "next": ["set_authorization", "validate_spec"],
    },
    "create_project": {
        "scope": "mcp:write",
        "example": '{"name": "Clinic", "description": "Booking backend"}',
        "next": ["create_entity", "get_project_status"],
    },
    "create_role": {
        "scope": "mcp:write",
        "example": '{"project_id": "<uuid>", "role": {"name": "doctor", "label": "Doctor"}}',
        "next": ["set_permissions", "set_auth_config"],
    },
    "update_role": {
        "scope": "mcp:write",
        "example": '{"project_id": "<uuid>", "name": "doctor", "changes": {"invite_only": true}}',
        "next": ["list_roles_and_permissions", "set_permissions"],
    },
    "set_auth_config": {
        "scope": "mcp:write",
        "example": (
            '{"project_id": "<uuid>", "config": {"enabled": true, '
            '"email_magic_link_enabled": false}}'
        ),
        "next": ["create_role", "set_permissions"],
    },
    "set_authorization": {
        "scope": "mcp:write",
        "example": '{"project_id": "<uuid>", "authorization": {"model": "rbac"}}',
        "next": ["validate_spec"],
    },
    "apply_op": {
        "scope": "mcp:write",
        "example": (
            '{"project_id": "<uuid>", "op_type": "add_entity", '
            '"payload": {"name": "Appointment"}, "dry_run": true}'
        ),
        "next": ["validate_spec", "undo_last_change"],
    },
    "put_behavior_block": {
        "scope": "mcp:write",
        "example": (
            '{"project_id": "<uuid>", "block": "events", "value": {"enabled": true}, '
            '"expected_version": 0}'
        ),
        "next": ["validate_spec", "get_project_status"],
    },
    "undo_last_change": {
        "scope": "mcp:write",
        "example": '{"project_id": "<uuid>"}',
        "next": ["redo_last_change", "list_spec_history"],
    },
    "redo_last_change": {
        "scope": "mcp:write",
        "example": '{"project_id": "<uuid>"}',
        "next": ["validate_spec"],
    },
    "apply_destructive_op": {
        "scope": "mcp:destructive",
        "example": (
            '{"project_id": "<uuid>", "op_type": "remove_field", '
            '"payload": {"entity": "Patient", "name": "nickname"}, "dry_run": true}'
        ),
        "next": ["validate_spec", "undo_last_change"],
    },
    "put_packs": {
        "scope": "mcp:destructive",
        "example": ('{"project_id": "<uuid>", "packs": {"booking": {}}, "dry_run": true}'),
        "next": ["validate_spec", "get_project_status"],
    },
    "generate_project": {
        "scope": "mcp:generate",
        "example": '{"project_id": "<uuid>"}',
        "next": ["list_generations", "get_project_status"],
    },
}

# Spec section -> how an MCP client edits it today. None = dashboard only (said honestly).
_OP_SECTIONS = ("state_machines", "settings", "sequences", "lists", "history", "hooks", "seed")
SECTION_TOOLS: dict[str, str | None] = {
    "project": "apply_op (update_entity does not rename the project; use the dashboard)",
    "entities": "create_entity / add_field / apply_op (add_entity, update_entity, ...)",
    "relations": "add_relation / apply_op (add_relation, update_relation)",
    "features": None,
    "auth": "set_auth_config",
    "authorization": "set_authorization (+ create_role, update_role, set_permissions)",
    **{s: "apply_op with op_type set_section" for s in _OP_SECTIONS},
    **{b: "put_behavior_block" for b in BLOCKS},
    "packs": "put_packs (destructive scope, dry run by default)",
}

# Never available over MCP, whatever the scope.
CANNOT_DO = [
    "Enter credentials: SMTP/SMS passwords, Stripe/GitHub/Twilio/Okta/Keycloak keys, key files. "
    "Tell the user to enter them in the dashboard.",
    "Manage members, API tokens or MCP grants, billing, admin, or delete a project.",
    "Run or edit the generated code, or read data of other projects/tenants.",
]

SCOPES = {
    "mcp:read": "read specs, status, history",
    "mcp:write": "create projects, change the model, roles, permissions, behaviour (editor role or higher)",
    "mcp:generate": "render the project zip",
    "mcp:destructive": "removes, packs rewrite, confirming access-widening edits (dry run first)",
}

TOPICS = ("sections", "packs", "blocks", "op_types", "tools", "limits")


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """First pydantic model inside `X | None` / `list[X]`."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        if arg is type(None):
            continue
        found = _model_of(arg)
        if found is not None:
            return found
    return None


def _summary(model: type[BaseModel] | None) -> str:
    doc = (model.__doc__ or "") if model is not None else ""
    return " ".join(doc.split())[:240]


def _kind(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    if origin in (list, typing.List):  # noqa: UP006
        return "list"
    if origin in (typing.Union, types.UnionType):
        return "object"
    return "object" if _model_of(annotation) is not None else "value"


def _sections() -> list[dict[str, Any]]:
    out = []
    for name, f in Spec.model_fields.items():
        if name == "spec_version":
            continue
        model = _model_of(f.annotation)
        tool = SECTION_TOOLS.get(name)
        out.append(
            {
                "section": name,
                "kind": _kind(f.annotation),
                "summary": _summary(model),
                "fields": sorted(model.model_fields) if model is not None else [],
                "edit_with": tool,
                "mcp_editable": tool is not None,
            }
        )
    return out


# One-line purpose for packs whose spec class has no docstring (parts/names stay from SpecPacks).
_PACK_SUMMARY = {
    "money": "Money pack: ledger, currency, reconciliation and invoicing.",
    "operations": "Operations pack: geo, location, matching and prediction blocks.",
    "ai": "AI pack: gateway, documents, knowledge (RAG), agents and evals, with a fake provider "
    "until keys are entered in the dashboard.",
}


def _packs() -> list[dict[str, Any]]:
    out = []
    for name, f in SpecPacks.model_fields.items():
        model = _model_of(f.annotation)
        parts = sorted(model.model_fields) if model is not None else []
        out.append(
            {
                "pack": name,
                "summary": _summary(model) or _PACK_SUMMARY.get(name, ""),
                "parts": parts,
                "can": f"generate {', '.join(parts)} when declared under packs.{name}"
                if parts
                else f"declared under packs.{name}",
                "cannot": "run without being declared; unknown options are refused",
                "edit_with": "put_packs",
            }
        )
    return out


def _blocks() -> list[dict[str, Any]]:
    return [
        {
            "block": b,
            "schema": cls,
            "edit_with": "put_behavior_block",
            "owner_only": b == "hook_effects",
            "secrets": "refused (secret_in_spec); enter them in the dashboard",
        }
        for b, cls in BLOCKS.items()
    ]


def _op_types() -> list[dict[str, Any]]:
    return [
        {
            "op_type": n,
            "destructive": n in DESTRUCTIVE_OPS,
            "tool": "apply_destructive_op" if n in DESTRUCTIVE_OPS else "apply_op",
            "summary": _summary(d.model),
        }
        for n, d in sorted(REGISTRY.items())
    ]


def describe_platform(topic: str | None = None) -> dict[str, Any]:
    if topic is not None and topic not in TOPICS:
        raise AppError(
            code="unknown_topic",
            message=f"topic must be one of {list(TOPICS)} (or omitted for everything)",
            status_code=422,
        )
    full: dict[str, Any] = {
        "sections": _sections(),
        "packs": _packs(),
        "blocks": _blocks(),
        "op_types": _op_types(),
        "tools": [{"tool": t, **h} for t, h in sorted(TOOL_HELP.items())],
        "limits": {"scopes": SCOPES, "cannot_do": CANNOT_DO},
    }
    out = full if topic is None else {topic: full[topic]}
    out["topics"] = list(TOPICS)
    out["next_tools"] = ["get_started", "list_projects"]
    return out


_PLAYBOOK: list[dict[str, Any]] = [
    {
        "goal": "Learn what the platform can build",
        "tools": ["describe_platform"],
        "notes": "Call once; use topic=packs|blocks|sections for a smaller answer.",
    },
    {
        "goal": "Pick the project to work in",
        "tools": ["list_projects", "create_project", "get_project_status"],
        "notes": "If list_projects is empty call create_project (name only is enough), then "
        "continue with the returned id.",
    },
    {
        "goal": "Model the data (entities, fields, relations)",
        "tools": ["create_entity", "add_field", "add_relation", "get_data_model"],
        "notes": "Fields: string|integer|boolean|float|decimal|date|datetime|text|uuid|json|enum.",
    },
    {
        "goal": "Turn on sign-in and create roles",
        "tools": ["set_auth_config", "create_role", "update_role", "get_auth_model"],
        "notes": "Send email_magic_link_enabled=false until the user has entered SMTP in the "
        "dashboard.",
    },
    {
        "goal": "Say who may do what",
        "tools": ["set_permissions", "set_authorization", "list_roles_and_permissions"],
        "notes": "Roles must exist first. Widening access needs confirm_weakening + "
        "mcp:destructive.",
    },
    {
        "goal": "Add behaviour (state machines, hooks, settings, sequences, lists, history, seed)",
        "tools": ["list_op_types", "apply_op", "put_behavior_block"],
        "notes": "set_section REPLACES the whole section: read get_project_spec first. "
        "Use dry_run=true to preview.",
    },
    {
        "goal": "Add domain packs (money, operations, booking, ai) if the app needs them",
        "tools": ["describe_platform", "put_packs"],
        "notes": "put_packs is destructive-scoped and dry_run defaults to true.",
    },
    {
        "goal": "Check everything is consistent",
        "tools": ["validate_spec", "get_project_status"],
        "notes": "Fix every issue before generating.",
    },
    {
        "goal": "Generate the backend",
        "tools": ["generate_project", "list_generations"],
        "notes": "Returns a download_url; fetch it with the same API token.",
    },
    {
        "goal": "Tell the user what only a human can do",
        "tools": ["list_secrets_needed", "get_project_status"],
        "notes": "Call list_secrets_needed (and read `missing` in get_project_status): credentials "
        "(SMTP/SMS, Stripe, Okta/Keycloak) are entered in the dashboard, never over MCP. Preview tools are not available yet.",
    },
]


def get_started() -> dict[str, Any]:
    return {
        "summary": "Empty org to a generated backend, in order. Re-read get_project_status "
        "after each step.",
        "steps": [{"step": i, **s} for i, s in enumerate(_PLAYBOOK, 1)],
        "rules": [
            "Never put a secret in any argument; it is refused.",
            "Removals and access-widening edits need the mcp:destructive scope and a dry run.",
            "On any error read `hint` and `next_tools` in the error body.",
        ],
        "next_tools": ["describe_platform", "list_projects"],
    }


# error code -> (hint, next tools). Unknown codes get the generic entry.
_ERROR_HINTS: dict[str, tuple[str, list[str]]] = {
    "unauthenticated": (
        "Send 'Authorization: Bearer bb_pat_...' with an API token from the dashboard.",
        ["describe_platform"],
    ),
    "insufficient_scope": (
        "The token lacks the scope this tool needs. Create a token with it in the dashboard "
        "(see describe_platform topic=limits).",
        ["describe_platform"],
    ),
    "password_change_required": (
        "The user must choose a new password in the dashboard first.",
        [],
    ),
    "not_found": (
        "No such project (or you may not see it). Use an id from list_projects.",
        ["list_projects"],
    ),
    "mcp_not_granted": (
        "The project owner must enable MCP for your membership in the dashboard.",
        ["list_projects"],
    ),
    "mcp_not_in_plan": ("MCP is not included in this organisation's plan.", []),
    "forbidden": (
        "Your project role is too low for this change (editor or higher; owner for hook_effects).",
        ["list_projects"],
    ),
    "not_allowed": ("Your role may not do this.", ["list_roles_and_permissions"]),
    "access_weakened": (
        "This edit gives a role more access. Review it with the user, then repeat with "
        "confirm_weakening=true on a token that has mcp:destructive.",
        ["list_roles_and_permissions", "get_project_spec"],
    ),
    "not_destructive": (
        "This op is not destructive: use apply_op.",
        ["apply_op", "list_op_types"],
    ),
    "unknown_block": (
        "Pick a block from describe_platform topic=blocks.",
        ["describe_platform"],
    ),
    "unknown_topic": ("Pick one of the listed topics.", ["describe_platform"]),
    "invalid_project_id": (
        "project_id must be the uuid returned by list_projects.",
        ["list_projects"],
    ),
    "invalid_reference": (
        "A referenced entity or role does not exist yet; create it first.",
        ["get_data_model", "list_roles_and_permissions"],
    ),
    "validation_error": (
        "Fix the fields named in `details`; list_op_types shows each payload schema.",
        ["list_op_types", "validate_spec"],
    ),
    "pinned_token": (
        "This API token is pinned to one project. Use an unpinned token to create projects.",
        [],
    ),
    "unknown_keys": (
        "Use only the listed keys.",
        ["get_auth_model", "list_roles_and_permissions"],
    ),
    "conflict": (
        "That name or slug is already taken; pick another one (or omit slug to derive a free one).",
        ["list_projects", "list_roles_and_permissions"],
    ),
    "project_limit": (
        "The organisation's plan allows no more projects. Ask the user to upgrade the plan or "
        "remove a project in the dashboard; use an existing project meanwhile.",
        ["list_projects"],
    ),
    "email_not_verified": ("The user must verify their e-mail in the dashboard.", []),
}
_GENERIC_HINT = (
    "Read the message; get_project_status shows the current state and the next step.",
    ["get_project_status", "get_started"],
)


def error_payload(exc: AppError) -> dict[str, Any]:
    """Uniform tool error: code, message, status, hint, next_tools (+ details)."""
    hint, nxt = _ERROR_HINTS.get(exc.code, _GENERIC_HINT)
    if exc.status_code == 422 and exc.code not in _ERROR_HINTS:
        hint, nxt = _ERROR_HINTS["validation_error"]
    err: dict[str, Any] = {
        "code": exc.code,
        "message": exc.message,
        "status": exc.status_code,
        "hint": hint,
        "next_tools": list(nxt),
    }
    if exc.details:
        err["details"] = exc.details
    return {"error": err}


def with_help(name: str, description: str) -> str:
    """Tool description = purpose + scope + example + next-tool hint."""
    h = TOOL_HELP.get(name)
    if h is None:
        return description
    nxt = ", ".join(h["next"])
    return f"{description} Scope: {h['scope']}. Example args: {h['example']}. Next tool: {nxt}."
