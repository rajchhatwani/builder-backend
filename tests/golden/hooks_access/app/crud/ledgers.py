"""Repository for Ledger (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.ledgers import Ledger


class LedgerRepository(_crud_base.Repository[Ledger]):
    model = Ledger
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
