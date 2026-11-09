"""Search with a permission filter (C21).

The filter is built from the access layers (object / row / field) and applied INSIDE the query,
not after it: a row a role may not read is never a candidate, so it cannot show up in the hits or
in the counts; a field a role may not read is never searched and never returned (otherwise the
query "salary:5000" would leak the value through a match). Adapters only index and rank:

    FtsAdapter         Postgres full-text semantics, the default (stand-in with the same contract)
    OpenSearchAdapter  a second engine behind the same interface (swap = same filtered set)

Policy models (abac / pbac) fail closed here unless an unconditional allow reaches the role:
a condition on a row cannot be pushed into an index without the engine, so it is not guessed.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.access_layers import AccessMatrix, _held, readable_fields
from app.core.enums import RowRule
from app.core.spec_models import Spec
from app.core.validation import ADMIN_ROLE

MAX_HITS = 100
_TOKEN = re.compile(r"[a-z0-9]+")
_SEARCHABLE = {"string", "text", "enum"}


@dataclass(frozen=True)
class RowScope:
    """Which rows of an entity a caller reaches. kind: all | owner | filter | none."""

    kind: str
    field: str | None = None
    value: str | None = None
    tenant: bool = False  # the entity is tenant-scoped: add tenant_id = caller's tenant

    def allows(self, row: Mapping[str, Any], subject: Mapping[str, Any]) -> bool:
        if self.kind == "none":
            return False
        if self.tenant and (
            subject.get("tenant_id") is None or row.get("tenant_id") != subject["tenant_id"]
        ):
            return False
        if self.kind == "owner":
            return subject.get("id") is not None and row.get("created_by_id") == subject["id"]
        if self.kind == "filter":
            return self.field is not None and str(row.get(self.field)) == self.value
        return True

    def sql(self) -> tuple[str, dict[str, Any]]:
        """The same rule as a WHERE fragment with named parameters (column names come from the
        validated spec, values are always bound)."""
        parts: list[str] = []
        if self.kind == "none":
            return "FALSE", {}
        if self.tenant:
            parts.append("tenant_id = :caller_tenant")
        if self.kind == "owner":
            parts.append("created_by_id = :caller_id")
        elif self.kind == "filter":
            parts.append(f'"{self.field}" = :filter_value')
        params = {"filter_value": self.value} if self.kind == "filter" else {}
        return (" AND ".join(parts) or "TRUE"), params


def row_scope(spec: Spec, entity: str, subject: Mapping[str, Any]) -> RowScope:
    """The rows `subject` ({id, roles, tenant_id}) may list. Unknown entity / no access = none."""
    matrix = AccessMatrix(spec)
    if entity not in matrix.entities:
        return RowScope("none")
    roles = [r for r in subject.get("roles") or [] if isinstance(r, str)]
    held: set[str] = set()
    for r in roles:
        held |= _held(r, matrix._parents)
    access, label = matrix._object(entity, "list", held)
    if access == "no" or (access == "conditional" and label == "policy"):
        return RowScope("none")  # fail closed: row conditions of policies are not pushed down
    auth = spec.auth
    tenant = bool(
        auth is not None
        and auth.multi_tenant
        and any(p.entity == entity and p.row_rule == RowRule.tenant for p in auth.permissions)
    )
    perm = None
    if auth is not None:
        perm = next((p for p in auth.permissions if p.entity == entity and p.operation == "list"), None)
    rule = perm.row_rule if perm is not None and perm.roles else None
    if rule == RowRule.owner:
        return RowScope("owner", tenant=tenant)
    if rule == RowRule.role_scoped:
        return RowScope("all" if ADMIN_ROLE in held else "owner", tenant=tenant)
    if rule == RowRule.custom_filter and perm is not None:
        return RowScope("filter", perm.custom_filter_field, perm.custom_filter_value, tenant)
    return RowScope("all", tenant=tenant)


def searchable_fields(spec: Spec, entity: str, subject: Mapping[str, Any]) -> list[str]:
    """Text fields the caller may read: the only ones a query can match and a hit can show."""
    readable = readable_fields(spec, entity, subject.get("roles") or [])
    ent = next((e for e in spec.entities if e.name == entity), None)
    if ent is None:
        return []
    return [f.name for f in ent.fields if f.name in readable and f.type in _SEARCHABLE]


def tokens(text: Any) -> list[str]:
    return _TOKEN.findall(str(text).lower())


class Adapter(Protocol):
    def search(
        self,
        rows: Sequence[Mapping[str, Any]],
        query: str,
        fields: Sequence[str],
        scope: RowScope,
        subject: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]: ...


class FtsAdapter:
    """All query words must appear (as whole words) in the readable fields; ranked by hits."""

    def search(self, rows, query, fields, scope, subject):  # type: ignore[no-untyped-def]
        words = tokens(query)
        if not words or not fields:
            return []
        scored: list[tuple[int, str, Mapping[str, Any]]] = []
        for row in rows:
            if not scope.allows(row, subject):  # filter first: hidden rows are never candidates
                continue
            bag = [t for f in fields for t in tokens(row.get(f, ""))]
            if all(w in bag for w in words):
                scored.append((-sum(bag.count(w) for w in words), str(row.get("id")), row))
        return [r for _, _, r in sorted(scored, key=lambda x: (x[0], x[1]))]


class OpenSearchAdapter:
    """Prefix matching over the same readable fields (a different engine, same filtered set)."""

    def search(self, rows, query, fields, scope, subject):  # type: ignore[no-untyped-def]
        words = tokens(query)
        if not words or not fields:
            return []
        out: list[tuple[int, str, Mapping[str, Any]]] = []
        for row in rows:
            if not scope.allows(row, subject):
                continue
            bag = [t for f in fields for t in tokens(row.get(f, ""))]
            if all(any(t.startswith(w) for t in bag) for w in words):
                out.append((-len(words), str(row.get("id")), row))
        return [r for _, _, r in sorted(out, key=lambda x: (x[0], x[1]))]


def search(
    spec: Spec,
    adapter: Adapter,
    rows: Iterable[Mapping[str, Any]],
    entity: str,
    query: str,
    subject: Mapping[str, Any],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """{hits, total}: hits carry only readable fields; total counts only rows the caller may see."""
    scope = row_scope(spec, entity, subject)
    fields = searchable_fields(spec, entity, subject)
    shown = readable_fields(spec, entity, subject.get("roles") or [])
    found = adapter.search(list(rows), query, fields, scope, subject)
    # Defence in depth: whatever an adapter returns is re-checked against the same scope.
    found = [r for r in found if scope.allows(r, subject)]
    hits = [
        {k: v for k, v in r.items() if k == "id" or k in shown}
        for r in found[: max(1, min(limit, MAX_HITS))]
    ]
    return {"hits": hits, "total": len(found)}
