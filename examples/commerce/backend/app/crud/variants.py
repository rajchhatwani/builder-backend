"""Repository for Variant (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.products import Product
from app.models.variants import Variant


class VariantRepository(_crud_base.Repository[Variant]):
    model = Variant
    soft_delete = False
    filterable = ("barcode", "sku")
    sortable = ("created_at", "position", "price")
    searchable = ("barcode", "sku", "title")
    eager = ("cart_lines", "inventory_levels", "order_lines")
    references = {"product_id": Product}
    many_to_many = {}
