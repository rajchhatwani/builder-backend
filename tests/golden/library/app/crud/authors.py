"""Repository for Author (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.authors import Author


class AuthorRepository(_crud_base.Repository[Author]):
    model = Author
    soft_delete = False
    filterable = ("name",)
    sortable = ("name", "rating")
    searchable = ("name",)
    eager = ("books",)
    references = {}
    many_to_many = {}
