"""Repository for Ticket (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.tickets import Ticket
from app.state_machines.hooks import hooks_for


class TicketRepository(_crud_base.Repository[Ticket]):
    model = Ticket
    soft_delete = False
    filterable = ("status",)
    sortable = ("priority",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = hooks_for("Ticket")
