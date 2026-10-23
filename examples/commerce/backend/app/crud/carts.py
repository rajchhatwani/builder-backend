"""Repository for Cart (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.carts import Cart
from app.models.customers import Customer


class CartRepository(_crud_base.Repository[Cart]):
    model = Cart
    soft_delete = False
    filterable = ("status", "token")
    sortable = ("created_at", "updated_at")
    searchable = ()
    eager = ("lines", "order")
    references = {"customer_id": Customer}
    many_to_many = {}
