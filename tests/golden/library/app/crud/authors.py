"""Repository for Author (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.authors import Author
from app.search import hooks as _search_hooks


class AuthorRepository(_crud_base.Repository[Author]):
    model = Author
    soft_delete = False
    filterable = ("name",)
    sortable = ("name", "rating")
    searchable = ("name",)
    eager = ("books",)
    references = {}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
AuthorRepository.hooks = _search_hooks.attach(
    "Author", ("name",), AuthorRepository.hooks
)
