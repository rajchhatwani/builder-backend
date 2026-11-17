"""Repository for Tag (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.products import Product
from app.models.tags import Tag
from app.search import hooks as _search_hooks


class TagRepository(_crud_base.Repository[Tag]):
    model = Tag
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ("name",)
    eager = ("products",)
    references = {}
    many_to_many = {"products": Product}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
TagRepository.hooks = _search_hooks.attach(
    "Tag", ("name",), TagRepository.hooks
)
