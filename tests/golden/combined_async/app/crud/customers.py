"""Repository for Customer (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.events import hooks as _event_hooks
from app.models.customers import Customer


class CustomerRepository(_crud_base.Repository[Customer]):
    model = Customer
    soft_delete = False
    filterable = ()
    sortable = ("created_at",)
    searchable = ()
    eager = ("orders",)
    references = {}
    many_to_many = {}


# Events last: they see the final state (automatic moves applied) and roll the write back if the outbox
# row cannot be written.
CustomerRepository.hooks = _event_hooks.attach("Customer", CustomerRepository.hooks)
