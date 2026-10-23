"""Repository for DiscountUsage (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.discount_usages import DiscountUsage
from app.models.discounts import Discount
from app.models.orders import Order


class DiscountUsageRepository(_crud_base.Repository[DiscountUsage]):
    model = DiscountUsage
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"discount_id": Discount, "order_id": Order}
    many_to_many = {}
