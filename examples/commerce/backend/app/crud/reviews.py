"""Repository for Review (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customers import Customer
from app.models.products import Product
from app.models.reviews import Review
from app.search import hooks as _search_hooks


class ReviewRepository(_crud_base.Repository[Review]):
    model = Review
    soft_delete = False
    filterable = ("rating", "status")
    sortable = ("created_at", "rating")
    searchable = ("body", "title")
    eager = ()
    references = {"customer_id": Customer, "product_id": Product}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
ReviewRepository.hooks = _search_hooks.attach(
    "Review", ("body", "title"), ReviewRepository.hooks
)
