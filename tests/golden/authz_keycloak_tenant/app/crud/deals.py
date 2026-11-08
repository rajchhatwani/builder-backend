"""Repository for Deal (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.deals import Deal


class DealRepository(_crud_base.Repository[Deal]):
    model = Deal
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
