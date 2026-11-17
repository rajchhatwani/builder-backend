"""Repository for Order (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.carts import Cart
from app.models.customers import Customer
from app.models.orders import Order
from app.models.shipping_rates import ShippingRate


class OrderRepository(_crud_base.Repository[Order]):
    model = Order
    soft_delete = False
    filterable = ("email", "financial_status", "fulfillment_status", "number", "source", "status")
    sortable = ("created_at", "number", "placed_at", "total")
    searchable = ("email", "note")
    eager = ("discount_usages", "events", "fulfillments", "lines", "refunds", "transactions")
    references = {"cart_id": Cart, "customer_id": Customer, "shipping_rate_id": ShippingRate}
    many_to_many = {}
