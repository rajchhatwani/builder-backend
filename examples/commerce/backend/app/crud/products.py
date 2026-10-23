"""Repository for Product (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.collections import Collection
from app.models.products import Product
from app.models.tags import Tag


class ProductRepository(_crud_base.Repository[Product]):
    model = Product
    soft_delete = True
    filterable = ("handle", "product_type", "status", "vendor")
    sortable = ("created_at", "published_at", "title", "updated_at")
    searchable = ("handle", "title", "vendor")
    eager = ("collections", "images", "reviews", "tags", "variants")
    references = {}
    many_to_many = {"collections": Collection, "tags": Tag}
