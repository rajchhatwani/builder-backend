"""Repository for Ticket (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.events import hooks as _event_hooks
from app.models.tickets import Ticket


class TicketRepository(_crud_base.Repository[Ticket]):
    model = Ticket
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}


# Events last: they see the final state (automatic moves applied) and roll the write back if the outbox
# row cannot be written.
TicketRepository.hooks = _event_hooks.attach("Ticket", TicketRepository.hooks)
