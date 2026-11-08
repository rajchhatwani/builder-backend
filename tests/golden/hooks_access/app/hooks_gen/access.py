"""Which rows a hook may read through `find_rows` (generated from the spec: change it in the builder).

A hook that declares `reads` does NOT get a back door around the access rules. For every entity it
reads, `find_rows` applies exactly what the entity's own list endpoint applies to the person whose
request runs the hook: their role permissions, the row rules (owner, tenant, custom filter), or the
abac / pbac policy decision. The `Access` is built by the same functions the routes use
(`build_access`), and the rows come from the entity's own repository.

Fail closed: no signed-in caller where the endpoint needs one, a caller whose roles or policies would
get a 403, no tenant where the endpoint is tenant-scoped, an entity without a read endpoint, or an
entity that is not listed here all end in `AccessDenied`. Nothing is returned in those cases.
"""

from typing import Any

from app.platform_sdk.env import AccessDenied

RULES: dict[str, dict[str, Any]] = {'Ledger': {'build': {'roles': ('admin',), 'tenant': True},
            'mode': 'roles',
            'needs_user': True,
            'op': 'list',
            'read': ('app.schemas.ledgers', 'LedgerRead'),
            'repo': ('app.crud.ledgers', 'LedgerRepository'),
            'tenant': True},
 'Note': {'build': {'admin_sees_all': True,
                    'owner': True,
                    'roles': ('admin', 'member'),
                    'tenant': True},
          'mode': 'roles',
          'needs_user': True,
          'op': 'list',
          'read': ('app.schemas.notes', 'NoteRead'),
          'repo': ('app.crud.notes', 'NoteRepository'),
          'tenant': True}}


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
            raise _denied()
        return build_access(caller, **rule["build"]).repo_kwargs  # type: ignore[no-any-return]
    except AppError as exc:
        raise _denied() from exc
