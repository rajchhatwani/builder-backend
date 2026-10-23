"""Repository for ShippingRate (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.shipping_rates import ShippingRate
from app.models.shipping_zones import ShippingZone


class ShippingRateRepository(_crud_base.Repository[ShippingRate]):
    model = ShippingRate
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("orders",)
    references = {"zone_id": ShippingZone}
    many_to_many = {}
