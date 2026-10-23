"""Repository for Refund (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.orders import Order
from app.models.refunds import Refund


class RefundRepository(_crud_base.Repository[Refund]):
    model = Refund
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("lines",)
    references = {"order_id": Order}
    many_to_many = {}
