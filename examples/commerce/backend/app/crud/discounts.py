"""Repository for Discount (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.discounts import Discount
from app.search import hooks as _search_hooks


class DiscountRepository(_crud_base.Repository[Discount]):
    model = Discount
    soft_delete = False
    filterable = ("active", "code", "kind")
    sortable = ()
    searchable = ("code", "title")
    eager = ("usages",)
    references = {}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
DiscountRepository.hooks = _search_hooks.attach(
    "Discount", ("code", "title"), DiscountRepository.hooks
)
