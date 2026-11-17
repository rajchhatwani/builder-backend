"""Repository for Variant (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.products import Product
from app.models.variants import Variant
from app.search import hooks as _search_hooks


class VariantRepository(_crud_base.Repository[Variant]):
    model = Variant
    soft_delete = False
    filterable = ("barcode", "sku")
    sortable = ("created_at", "position", "price")
    searchable = ("barcode", "sku", "title")
    eager = ("cart_lines", "inventory_levels", "order_lines")
    references = {"product_id": Product}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
VariantRepository.hooks = _search_hooks.attach(
    "Variant", ("barcode", "sku", "title"), VariantRepository.hooks
)
