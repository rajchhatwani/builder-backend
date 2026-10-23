"""Repository for Order (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.orders import Order


class OrderRepository(_crud_base.Repository[Order]):
    model = Order
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
