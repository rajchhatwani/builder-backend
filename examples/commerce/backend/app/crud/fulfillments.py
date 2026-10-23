"""Repository for Fulfillment (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.fulfillments import Fulfillment
from app.models.locations import Location
from app.models.orders import Order


class FulfillmentRepository(_crud_base.Repository[Fulfillment]):
    model = Fulfillment
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("lines",)
    references = {"location_id": Location, "order_id": Order}
    many_to_many = {}
