"""Repository for Order (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customers import Customer
from app.models.orders import Order


class OrderRepository(_crud_base.Repository[Order]):
    model = Order
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"customer_id": Customer}
    many_to_many = {}
