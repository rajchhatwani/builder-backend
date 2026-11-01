"""Repository for Order (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.events import hooks as _event_hooks
from app.models.customers import Customer
from app.models.orders import Order


class OrderRepository(_crud_base.Repository[Order]):
    model = Order
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"customer_id": Customer}
    many_to_many = {}


# Events last: they see the final state (automatic moves applied) and roll the write back if the outbox
# row cannot be written.
OrderRepository.hooks = _event_hooks.attach("Order", OrderRepository.hooks)
