"""Repository for Item (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.items import Item


class ItemRepository(_crud_base.Repository[Item]):
    model = Item
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
