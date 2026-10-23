"""Repository for Page (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.pages import Page


class PageRepository(_crud_base.Repository[Page]):
    model = Page
    soft_delete = False
    filterable = ("handle", "published")
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
