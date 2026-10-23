"""Repository for FulfillmentLine (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.fulfillment_lines import FulfillmentLine
from app.models.fulfillments import Fulfillment
from app.models.order_lines import OrderLine


class FulfillmentLineRepository(_crud_base.Repository[FulfillmentLine]):
    model = FulfillmentLine
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"fulfillment_id": Fulfillment, "order_line_id": OrderLine}
    many_to_many = {}
