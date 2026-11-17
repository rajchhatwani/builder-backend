"""Repository for Tag (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.products import Product
from app.models.tags import Tag


class TagRepository(_crud_base.Repository[Tag]):
    model = Tag
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ("name",)
    eager = ("products",)
    references = {}
    many_to_many = {"products": Product}
