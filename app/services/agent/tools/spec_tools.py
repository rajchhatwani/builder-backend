"""Class S: spec-draft edits through the typed operations registry. No new business logic: every
tool maps to one `OpsService.apply_op` call, and a 422 becomes a RuleFailure the agent can repair.

Anything that touches auth, access or tenancy is refused here and belongs to the S! tools."""

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
from app.services.agent.draft import add_draft_op, run_spec
from app.services.ops.registry import SECTIONS, section_adapter

from ._common import app_error_failure, fail, has_key, refuse

SECURITY_SECTIONS = frozenset(
    {"auth", "authorization", "access", "tenancy", "tenant", "tenants", "permissions", "roles", "rbac", "abac",
     "pbac", "security"}
)  # fmt: skip
S_BANG_HINT = (
    "this weakens or changes security; the agent cannot do it. Use weaken_access_rule or "
    "change_tenancy_mode, which ask a human"
)


async def _apply(ctx: ToolContext, tool: str, op_type: str, payload: dict[str, Any], summary: str) -> ToolResult:
    try:
        seq = await add_draft_op(ctx.session, ctx.run_id, ctx.project_id, op_type, payload)
    except AppError as exc:
        return ToolResult(ok=False, failures=(app_error_failure(tool, exc),))
    return ToolResult(ok=True, data={"op_type": op_type, "draft_seq": seq, "summary": summary})


async def add_entity(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    ent = args["entity"]
    return await _apply(ctx, "add_entity", "add_entity", {"entity": ent}, f"added entity {ent.get('name')}")


async def add_field(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    _check_security_keys("add_field", args["field"])
    payload = {"entity": args["entity"], "field": args["field"]}
    if args.get("index") is not None:
        payload["index"] = args["index"]
    return await _apply(ctx, "add_field", "add_field", payload,
                        f"added field {args['field'].get('name')} to {args['entity']}")  # fmt: skip


async def _current_field(ctx: ToolContext, entity: str, name: str) -> dict[str, Any] | None:
    spec = await run_spec(ctx.session, ctx.run_id, ctx.project_id)
    for e in spec.entities:
        if e.name == entity:
            for f in e.fields:
                if f.name == name:
                    return f.model_dump(mode="json")
    return None


def weakening(current: dict[str, Any], changes: dict[str, Any]) -> list[str]:
    """Changes that loosen a constraint or can lose data: unique/required off, shorter max_length, new type."""
    out = []
    for flag in ("unique", "required"):
        if flag in changes and current.get(flag) and not changes[flag]:
            out.append(f"{flag} off")
    if "max_length" in changes:
        old, new = current.get("max_length"), changes["max_length"]
        if old is not None and (new is None or new < old):
            out.append("max_length reduced")
    if "type" in changes and changes["type"] != current.get("type"):
        out.append("type changed")
    for key in ("min_value", "max_value", "default"):
        # a first bound/default on a field that had none only adds a rule: that is the normal validation-rule edit
        if key in changes and changes[key] != current.get(key) and current.get(key) is not None:
            out.append(f"{key} changed")
    if "enum_values" in changes and changes["enum_values"] != current.get("enum_values"):
        old_vals, new_vals = current.get("enum_values"), changes["enum_values"]
        if old_vals is not None and (new_vals is None or not set(old_vals) <= set(new_vals)):
            out.append("enum values removed")  # S1-012: rows holding a removed value become invalid
    if "indexed" in changes and current.get("indexed") and not changes["indexed"]:
        out.append("indexed off")
    if "name" in changes and changes["name"] != current.get("name"):
        out.append("renamed (column drop and add)")
    return out


def _check_security_keys(tool: str, obj: Any) -> None:
    key = has_key(obj)
    if key:
        raise refuse("tool_s_bang", tool, "no auth/access/tenancy content", f"key '{key[:30]}'", S_BANG_HINT)


async def update_field(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    _check_security_keys("update_field", args["changes"])
    current = await _current_field(ctx, args["entity"], args["name"])
    if current is not None:
        risky = weakening(current, args["changes"])
        if risky:
            return _ask_human("update_field", f"change {args['entity']}.{args['name']}: {', '.join(risky)}",
                              entity=args["entity"], name=args["name"], changes=args["changes"], risks=risky)  # fmt: skip
    payload = {"entity": args["entity"], "name": args["name"], "changes": args["changes"]}
    return await _apply(ctx, "update_field", "update_field", payload,
                        f"changed {sorted(args['changes'])} on {args['entity']}.{args['name']}")  # fmt: skip


def _ask_human(tool: str, subject: str, **payload: Any) -> ToolResult:
    return ToolResult(
        ok=True,
        data={"status": "approval_required", "executed": False},
        approval=ApprovalRequest(ApprovalKind.D, subject, {"op_type": tool, **payload}),
    )


async def add_relation(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    rel = args["relation"]
    _check_security_keys("add_relation", rel)
    if str(rel.get("on_delete", "")).lower() == "cascade":
        return _ask_human("add_relation", "add a relation that deletes related rows on delete (cascade)",
                          relation=rel)  # fmt: skip
    return await _apply(ctx, "add_relation", "add_relation", {"relation": rel},
                        f"added relation {rel.get('from_entity')}.{rel.get('from_name')} -> {rel.get('to_entity')}")  # fmt: skip


async def _current_hooks(ctx: ToolContext) -> dict[str, dict[str, Any]]:
    spec = await run_spec(ctx.session, ctx.run_id, ctx.project_id)
    return {h.name: h.model_dump(mode="json") for h in spec.hooks}


def _check_section(args: dict[str, Any]) -> None:
    section = str(args["section"])
    if section.lower() in SECURITY_SECTIONS:
        raise refuse("tool_s_bang", f"set_section:{section[:40]}", "a behaviour section", "auth/access/tenancy", S_BANG_HINT)
    if section not in SECTIONS:
        raise refuse("section_unknown", f"set_section:{section[:40]}", f"one of {list(SECTIONS)}", section[:40], "call list_blocks")
    key = has_key(args["items"])
    if key:
        raise refuse("tool_s_bang", f"set_section:{section}", "no auth/access/tenancy content", f"item key '{key[:30]}'", S_BANG_HINT)


ENTITY_SECTIONS = {"state_machines": "entity", "history": "entity"}
ID_KEYS = {"hooks": "name", "settings": "key", "sequences": "name", "lists": "name", "seed": "name",
           "state_machines": "entity", "history": "entity"}  # fmt: skip


def _norm(section: str, item: dict[str, Any]) -> dict[str, Any]:
    """The item with every default filled in, so equal meaning compares equal."""
    try:
        done = section_adapter(section).validate_python([item])[0].model_dump(mode="json")
    except Exception:
        done = dict(item)
    done.pop("author", None)
    return dict(done)


async def _current_section(ctx: ToolContext, section: str) -> list[dict[str, Any]]:
    spec = await run_spec(ctx.session, ctx.run_id, ctx.project_id)
    return [m.model_dump(mode="json") for m in getattr(spec, section)]


async def scope_set_section(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    """Every item the call adds, changes or drops must belong to the plan."""
    _check_section(args)
    plan = ctx.plan
    assert plan is not None
    section, idk = args["section"], ID_KEYS[args["section"]]
    new: dict[str, dict[str, Any]] = {}
    for item in args["items"]:
        if not isinstance(item.get(idk), str) or not item[idk]:
            raise refuse("tool_input", f"set_section:{section}", f"every item has a '{idk}'", "item without it")
        new[item[idk]] = item
    cur = {str(i[idk]): i for i in await _current_section(ctx, section)}
    removed = sorted(set(cur) - set(new))
    changed = sorted(k for k in set(cur) & set(new) if _norm(section, cur[k]) != _norm(section, new[k]))
    added = sorted(set(new) - set(cur))
    if section == "hooks":
        for name in removed:
            return ("hook", name)
        for name in changed + added:
            if name not in plan.hooks:
                return ("hook", name)
            point_entity = str(new[name].get("point", "")).split(".")[0]
            reads = [str(r) for r in new[name].get("reads") or []]
            for ent in [point_entity, *reads]:
                if ent not in plan.entities:
                    return ("entity", ent)
        return None
    if section in ENTITY_SECTIONS:
        for ent in removed + changed + added:
            if ent not in plan.entities:
                return ("entity", ent)
        return None
    # global sections (settings, sequences, lists, seed): the plan must be non-empty, only NEW
    # items may be added; an existing item is never changed or dropped by the agent.
    if not (plan.entities or plan.hooks):
        return ("plan", f"{section} (empty plan)")
    for key in removed + changed:
        return ("section_item", f"{section}:{key}")
    return None


def _same(current: dict[str, Any], item: dict[str, Any]) -> bool:
    return all(current.get(k) == v for k, v in item.items() if k != "author")


async def set_section(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    section, items = args["section"], args["items"]
    if section == "hooks":
        current = await _current_hooks(ctx)
        names = {str(i.get("name", "")) for i in items}
        gone = sorted(set(current) - names)
        if gone:
            return fail("tool_removal", "set_section:hooks", "no hook removed", f"would remove {gone}",
                        "removing a hook is not an agent action; keep it in the list")  # fmt: skip
        fixed = []
        for item in items:
            known = current.get(str(item.get("name", "")))
            # The agent can neither claim "trusted" nor clear its own mark: new hooks are "ai",
            # existing hooks keep the author they have unless the content changes (then "ai").
            author = "ai" if known is None or not _same(known, item) else known.get("author")
            fixed.append({**item, "author": author})
        items = fixed
    return await _apply(ctx, "set_section", "set_section", {"section": section, "items": items},
                        f"replaced section {section} ({len(items)} item(s))")  # fmt: skip


async def _scope_entity_arg(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    name = str(args["entity"])
    return None if name in ctx.plan.entities else ("entity", name)


async def _scope_add_entity(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    name = str(args["entity"].get("name", ""))
    if has_key(args["entity"]):
        raise refuse("tool_s_bang", "add_entity", "no tenancy/access settings", "security keys in entity", S_BANG_HINT)
    return None if name in ctx.plan.entities else ("entity", name)


async def _scope_add_relation(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    for key in ("from_entity", "to_entity"):
        name = str(args["relation"].get(key, ""))
        if name not in ctx.plan.entities:
            return ("entity", name)
    return None


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_NAME = {"type": "string", "minLength": 1, "maxLength": 80}
_OBJ = {"type": "object"}
S = PermissionClass.S
TOOLS: list[Tool] = [
    Tool("add_entity", "Add an entity (name and optional fields/options) to the spec draft.",
         _obj({"entity": _OBJ}, ["entity"]), S, add_entity),
    Tool("add_field", "Add a field to an entity of the spec draft.",
         _obj({"entity": _NAME, "field": _OBJ, "index": {"type": "integer", "minimum": 0}}, ["entity", "field"]),
         S, add_field),
    Tool("update_field", "Change attributes of an existing field.",
         _obj({"entity": _NAME, "name": _NAME, "changes": _OBJ}, ["entity", "name", "changes"]), S, update_field),
    Tool("add_relation", "Add a relation between two entities.",
         _obj({"relation": _OBJ}, ["relation"]), S, add_relation),
    Tool("set_section",
         "Replace one behaviour section (state_machines, settings, sequences, lists, history, hooks, seed). "
         "Never for auth, access or tenancy.",
         _obj({"section": {"type": "string", "maxLength": 40}, "items": {"type": "array", "maxItems": 100,
                                                                         "items": _OBJ}}, ["section", "items"]),
         S, set_section),
]  # fmt: skip
SCOPES: dict[str, Any] = {
    "add_entity": _scope_add_entity,
    "add_field": _scope_entity_arg,
    "update_field": _scope_entity_arg,
    "add_relation": _scope_add_relation,
    "set_section": scope_set_section,
}
