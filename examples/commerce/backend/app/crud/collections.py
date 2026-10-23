"""Repository for Collection (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.collections import Collection
from app.models.products import Product


class CollectionRepository(_crud_base.Repository[Collection]):
    model = Collection
    soft_delete = True
    filterable = ("handle", "kind", "published")
    sortable = ("created_at", "title")
    searchable = ("handle", "title")
    eager = ("children", "products")
    references = {"parent_id": Collection}
    many_to_many = {"products": Product}
