"""Repository for Customer (generated). Add custom queries by subclassing in your own module."""

from typing import Any

from app.crud import _base as _crud_base
from app.events import hooks as _event_hooks
from app.models.customers import Customer
from app.regulated import crypto as _regulated_crypto


class CustomerRepository(_crud_base.Repository[Customer]):
    model = Customer
    soft_delete = False
    filterable = ("email",)
    sortable = ("created_at",)
    searchable = ()
    eager = ("orders",)
    references = {}
    many_to_many = {}

    # Equality filters on searchable protected fields go through the blind index (`<field>_bidx`), under every ring key.
    blind_indexed = ("email",)

    def _conditions(self, filters: dict[str, Any], search: str | None) -> list[Any]:
        plain = {k: v for k, v in filters.items() if k not in self.blind_indexed}
        conditions = super()._conditions(plain, search)
        for name in self.blind_indexed:
            if name in filters:
                hashes = _regulated_crypto.blind_indexes(self.model.__tablename__, name, str(filters[name]))
                conditions.append(self._col(name + "_bidx").in_(hashes))
        return conditions


# Events last: they see the final state (automatic moves applied) and roll the write back if the outbox
# row cannot be written.
CustomerRepository.hooks = _event_hooks.attach("Customer", CustomerRepository.hooks)
