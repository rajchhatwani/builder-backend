"""Repository for Ticket (generated). Add custom queries by subclassing in your own module."""

from app.change_history.hooks import hooks_for as history_hooks_for
from app.change_history.hooks import merge_hooks
from app.crud import _base as _crud_base
from app.models.tickets import Ticket
from app.state_machines.hooks import hooks_for as machine_hooks_for


class TicketRepository(_crud_base.Repository[Ticket]):
    model = Ticket
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = merge_hooks(machine_hooks_for("Ticket"), history_hooks_for("Ticket"))
