# ruff: noqa: E501
"""Declared renames: the only way a rename is ever applied. Nothing is guessed."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .model import MigrationPlanError


class Rename(BaseModel):
    """`{"kind": "entity", "from": "A", "to": "B"}` or
    `{"kind": "field", "entity": "<entity, new or old name>", "from": "a", "to": "b"}`.
    `kind` may be omitted: a hint with an `entity` key is a field rename, otherwise an entity rename."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["entity", "field"]
    entity: str | None = None
    from_: str
    to: str

    @classmethod
    def parse(cls, raw: "Rename | dict[str, Any]") -> "Rename":
        if isinstance(raw, Rename):
            return raw
        if not isinstance(raw, dict):
            raise MigrationPlanError(f"rename hint must be an object, got {type(raw).__name__}")
        data = dict(raw)
        if "from" in data:
            data["from_"] = data.pop("from")
        data.setdefault("kind", "field" if data.get("entity") else "entity")
        try:
            r = cls.model_validate(data)
        except ValidationError as exc:
            raise MigrationPlanError(f"invalid rename hint {raw!r}: {exc.errors()[0]['msg']}") from exc
        if r.kind == "field" and not r.entity:
            raise MigrationPlanError(f"field rename needs an 'entity': {raw!r}")
        if not r.from_ or not r.to or r.from_ == r.to:
            raise MigrationPlanError(f"rename needs different non-empty 'from' and 'to': {raw!r}")
        return r


def parse_renames(raw: list[Any] | None) -> list[Rename]:
    out = [Rename.parse(r) for r in (raw or [])]
    seen: set[tuple[str, str | None, str]] = set()
    for r in out:
        key = (r.kind, r.entity, r.from_)
        if key in seen:
            raise MigrationPlanError(f"duplicate rename for {r.from_!r}")
        seen.add(key)
    return out
