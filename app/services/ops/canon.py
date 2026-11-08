"""Canonical form of a spec: the bytes every op-log hash and "byte-identical" claim refers to.

`SpecService.assemble` already emits entities, fields and relations in a fixed order. Two lists
are not stable across a delete-and-recreate (an undo): permissions are read in entity-id order,
and ids are new after a re-create. Their order carries no meaning, so the canonical form sorts
them by (entity, operation). Nothing else is changed: keys sorted, no whitespace, ASCII only.
"""

import hashlib
import json

from app.core.spec_models import Spec


def normalize(spec: Spec) -> Spec:
    out = spec.model_copy(deep=True)
    out.entities.sort(key=lambda e: e.name)
    out.relations.sort(key=lambda r: (r.from_entity, r.from_name, r.to_entity))
    if out.auth is not None:
        out.auth.permissions.sort(key=lambda p: (p.entity, p.operation))
    return out


def canonical_bytes(spec: Spec) -> bytes:
    return json.dumps(
        normalize(spec).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def canonical_hash(spec: Spec) -> str:
    return hashlib.sha256(canonical_bytes(spec)).hexdigest()
