"""Repository for OrderEvent (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.order_events import OrderEvent
from app.models.orders import Order


class OrderEventRepository(_crud_base.Repository[OrderEvent]):
    model = OrderEvent
    soft_delete = False
    filterable = ()
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"order_id": Order}
    many_to_many = {}
