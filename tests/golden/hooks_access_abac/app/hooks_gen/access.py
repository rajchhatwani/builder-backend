"""Which rows a hook may read through `find_rows` (generated from the spec: change it in the builder).

A hook that declares `reads` does NOT get a back door around the access rules. For every entity it
reads, `find_rows` applies exactly what the entity's own list endpoint applies to the person whose
request runs the hook: their role permissions, the row rules (owner, tenant, custom filter), or the
abac / pbac policy decision. The `Access` is built by the same functions the routes use
(`build_access`, `PolicyBinding`), and the rows come from the entity's own repository.

Fail closed: no signed-in caller where the endpoint needs one, a caller whose roles or policies would
get a 403, no tenant where the endpoint is tenant-scoped, an entity without a read endpoint, or an
entity that is not listed here all end in `AccessDenied`. Nothing is returned in those cases.
"""

from typing import Any

from app.platform_sdk.env import AccessDenied

RULES: dict[str, dict[str, Any]] = {'Ticket': {'build': {},
            'mode': 'policy',
            'needs_user': True,
            'op': 'list',
            'read': ('app.schemas.tickets', 'TicketRead'),
            'repo': ('app.crud.tickets', 'TicketRepository'),
            'tenant': False}}


def rule_for(entity: str) -> dict[str, Any]:
    rule = RULES.get(entity)
    if rule is None or rule["mode"] == "deny":
        raise AccessDenied("this hook may not read that entity")
    return rule


def _denied() -> AccessDenied:
    return AccessDenied("the signed-in person may not read that entity")


def repo_kwargs(entity: str, caller: Any) -> dict[str, Any]:
    """The keyword arguments the entity's repository gets for `caller` (what the list route passes)."""
    from app.auth.access import build_access
    from app.core.errors import AppError

    rule = rule_for(entity)
    if rule["mode"] == "open" and not rule["needs_user"]:
        return {}
    if rule["needs_user"] and caller is None:
        raise _denied()
    if rule["tenant"] and getattr(caller, "tenant_id", None) is None:
        raise _denied()
    try:
        if rule["mode"] == "policy":
            return _policy_kwargs(entity, rule, caller)
        return build_access(caller, **rule["build"]).repo_kwargs  # type: ignore[no-any-return]
    except AppError as exc:
        raise _denied() from exc


def _policy_kwargs(entity: str, rule: dict[str, Any], caller: Any) -> dict[str, Any]:
    import dataclasses
    from datetime import UTC, datetime

    import sqlalchemy as sa

    from app.auth import authorize
    from app.auth.access import build_access
    from app.auth.policy import Context, plan

    # The request is gone, so facts about it (the client address) are unknown: a policy that needs
    # them is not satisfied.
    moment = datetime.now(UTC)
    env = {"hour_utc": moment.hour, "weekday_utc": moment.weekday(), "client_ip": None}
    context = Context(subject=authorize.subject_of(caller), env=env)
    decision = plan(authorize.POLICY_SET, context, entity, rule["op"], sa.column)
    if not decision.allowed:
        raise _denied()
    access = dataclasses.replace(
        build_access(caller, tenant=rule["tenant"]),
        policy=authorize.PolicyBinding(entity, rule["op"], context),
    )
    return access.repo_kwargs  # type: ignore[no-any-return]
