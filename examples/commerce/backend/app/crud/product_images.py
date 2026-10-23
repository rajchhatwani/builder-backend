"""Repository for ProductImage (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.product_images import ProductImage
from app.models.products import Product


class ProductImageRepository(_crud_base.Repository[ProductImage]):
    model = ProductImage
    soft_delete = False
    filterable = ()
    sortable = ("position",)
    searchable = ()
    eager = ()
    references = {"product_id": Product}
    many_to_many = {}
