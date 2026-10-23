"""Repository for ShippingZone (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.shipping_zones import ShippingZone


class ShippingZoneRepository(_crud_base.Repository[ShippingZone]):
    model = ShippingZone
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("rates",)
    references = {}
    many_to_many = {}
