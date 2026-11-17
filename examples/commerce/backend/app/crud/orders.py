"""Repository for Order (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.carts import Cart
from app.models.customers import Customer
from app.models.orders import Order
from app.models.shipping_rates import ShippingRate
from app.search import hooks as _search_hooks


class OrderRepository(_crud_base.Repository[Order]):
    model = Order
    soft_delete = False
    filterable = ("email", "financial_status", "fulfillment_status", "number", "source", "status")
    sortable = ("created_at", "number", "placed_at", "total")
    searchable = ("email", "note")
    eager = ("discount_usages", "events", "fulfillments", "lines", "refunds", "transactions")
    references = {"cart_id": Cart, "customer_id": Customer, "shipping_rate_id": ShippingRate}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
OrderRepository.hooks = _search_hooks.attach(
    "Order", ("email", "note"), OrderRepository.hooks
)
