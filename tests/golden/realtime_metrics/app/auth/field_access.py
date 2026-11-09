"""Field-level access (generated from spec.authorization.field_access).

RULES: entity -> field -> (read roles, write roles). None = the object permission decides; a list
restricts the field to holders of one of those roles (an empty list = nobody). Roles are held
through inheritance (effective_roles). Someone who is not signed in holds no roles.

A field the caller may not read is left out of every response (the key is missing, never null),
and cannot be used to filter, sort or search. A body that sets a field the caller may not write is
refused with 403 and nothing is written.
"""

from typing import Any

from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError

RULES: dict[str, dict[str, tuple[tuple[str, ...] | None, tuple[str, ...] | None]]] = {
    'Expense': {
        'cost_basis': (('admin',), ('admin',)),
    },
}


def _held(user: AuthUser | None) -> set[str]:
    return effective_roles(user.roles) if user is not None else set()


def _hidden(entity: str, user: AuthUser | None, index: int) -> frozenset[str]:
    held = _held(user)
    out: set[str] = set()
    for name, rule in RULES.get(entity, {}).items():
        allowed = rule[index]
        if allowed is not None and not held & set(allowed):
            out.add(name)
    return frozenset(out)


def hidden_read(entity: str, user: AuthUser | None) -> frozenset[str]:
    """Fields of `entity` this caller may not read."""
    return _hidden(entity, user, 0)


def hidden_write(entity: str, user: AuthUser | None) -> frozenset[str]:
    """Fields of `entity` this caller may not write."""
    return _hidden(entity, user, 1)


def shape[T](entity: str, user: AuthUser | None, item: T) -> T:
    """Mark the hidden fields of a Read object as unset, so `response_model_exclude_unset=True`
    leaves the key out of the response."""
    hidden = hidden_read(entity, user)
    if hidden:
        item.model_fields_set.difference_update(hidden)  # type: ignore[attr-defined]
    return item


def forbidden() -> AppError:
    return AppError("forbidden", "you do not have permission to do that", 403)


def payload(entity: str, user: AuthUser | None, body: Any, mode: str) -> dict[str, Any]:
    """The values to write from a request body. Setting a field the caller may not write is a 403.

    mode is create | replace | update. A replace leaves fields the caller may not write as they
    are (the body's defaults must not overwrite them)."""
    hidden = hidden_write(entity, user)
    if hidden & body.model_fields_set:
        raise forbidden()
    if mode == "update":
        return dict(body.model_dump(exclude_unset=True))
    data = dict(body.model_dump())
    if mode == "replace":
        for name in hidden:
            data.pop(name, None)
    return data


class HiddenFieldsMixin:
    """Repository mixin: hidden fields cannot be filtered on, sorted by or searched."""

    searchable: tuple[str, ...]

    def __init__(self, *args: Any, hidden_fields: frozenset[str] = frozenset(), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.hidden_fields = frozenset(hidden_fields)

    def _order_by(self, sort: str | None) -> list[Any]:
        for term in (t.strip() for t in (sort or "").split(",") if t.strip()):
            if term.lstrip("-") in self.hidden_fields:
                raise forbidden()
        return super()._order_by(sort)  # type: ignore[misc, no-any-return]

    def _conditions(self, filters: dict[str, Any], search: str | None) -> list[Any]:
        if self.hidden_fields & set(filters):
            raise forbidden()
        if self.hidden_fields and search:
            self.searchable = tuple(n for n in type(self).searchable if n not in self.hidden_fields)
            try:
                return super()._conditions(filters, search)  # type: ignore[misc, no-any-return]
            finally:
                del self.searchable
        return super()._conditions(filters, search)  # type: ignore[misc, no-any-return]
