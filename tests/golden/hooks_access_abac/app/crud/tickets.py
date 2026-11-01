"""Repository for Ticket (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.hooks_gen import registry as custom_hooks
from app.models.tickets import Ticket


class TicketRepository(_crud_base.Repository[Ticket]):
    model = Ticket
    soft_delete = False
    filterable = ("status",)
    sortable = ("priority",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = custom_hooks.merge_hooks(
        custom_hooks.hooks_for("Ticket"),
    )
