"""Repository for Product (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.products import Product


class ProductRepository(_crud_base.Repository[Product]):
    model = Product
    soft_delete = False
    filterable = ()
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
