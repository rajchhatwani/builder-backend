"""Repository for Customer (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customers import Customer


class CustomerRepository(_crud_base.Repository[Customer]):
    model = Customer
    soft_delete = True
    filterable = ("accepts_marketing", "email", "state")
    sortable = ("created_at", "orders_count", "total_spent")
    searchable = ("email", "first_name", "last_name", "phone")
    eager = ("addresses", "carts", "gift_cards", "orders", "reviews")
    references = {}
    many_to_many = {}
