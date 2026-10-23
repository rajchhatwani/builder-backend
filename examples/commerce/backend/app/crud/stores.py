"""Repository for Store (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.stores import Store


class StoreRepository(_crud_base.Repository[Store]):
    model = Store
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
