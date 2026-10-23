"""Repository for Discount (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.discounts import Discount


class DiscountRepository(_crud_base.Repository[Discount]):
    model = Discount
    soft_delete = False
    filterable = ("active", "code", "kind")
    sortable = ()
    searchable = ("code", "title")
    eager = ("usages",)
    references = {}
    many_to_many = {}
