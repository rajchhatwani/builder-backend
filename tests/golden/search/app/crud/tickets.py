"""Repository for Ticket (generated). Add custom queries by subclassing in your own module."""

from app.auth.field_access import HiddenFieldsMixin
from app.crud import _base as _crud_base
from app.models.tickets import Ticket
from app.search import hooks as _search_hooks


class TicketRepository(HiddenFieldsMixin, _crud_base.Repository[Ticket]):
    model = Ticket
    soft_delete = True
    filterable = ("title",)
    sortable = ("title",)
    searchable = ("internal_note", "title")
    eager = ()
    references = {}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
TicketRepository.hooks = _search_hooks.attach(
    "Ticket", ("internal_note", "title"), TicketRepository.hooks
)
