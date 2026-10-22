"""Repository for Shelf (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.shelves import Shelf


class ShelfRepository(_crud_base.Repository[Shelf]):
    model = Shelf
    soft_delete = False
    filterable = ("label",)
    sortable = ()
    searchable = ()
    eager = ("books_on_shelf",)
    references = {}
    many_to_many = {}
