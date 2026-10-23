"""Repository for OrderLine (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.order_lines import OrderLine
from app.models.orders import Order
from app.models.variants import Variant


class OrderLineRepository(_crud_base.Repository[OrderLine]):
    model = OrderLine
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("fulfillment_lines", "refund_lines")
    references = {"order_id": Order, "variant_id": Variant}
    many_to_many = {}
